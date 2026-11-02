use serde::{de::DeserializeOwned, Serialize};
use std::fs;
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::sync::Mutex;

static WRITE_LOCK: Mutex<()> = Mutex::new(());

pub struct Loaded<T> {
    pub value: Option<T>,
    pub recovered: bool,
}

fn backup_path(path: &Path) -> PathBuf {
    let mut name = path.as_os_str().to_os_string();
    name.push(".bak");
    name.into()
}

fn recovery_path(path: &Path) -> PathBuf {
    let mut name = path.as_os_str().to_os_string();
    name.push(".recovery");
    name.into()
}

fn read<T: DeserializeOwned>(path: &Path) -> io::Result<T> {
    let bytes = fs::read(path)?;
    serde_json::from_slice(&bytes).map_err(|error| {
        io::Error::new(
            io::ErrorKind::InvalidData,
            format!("{:?}", error.classify()),
        )
    })
}

fn replace(path: &Path, bytes: &[u8]) -> io::Result<()> {
    let parent = path
        .parent()
        .ok_or_else(|| io::Error::other("Missing parent directory"))?;
    fs::create_dir_all(parent)?;
    let mut temporary = tempfile::NamedTempFile::new_in(parent)?;
    temporary.write_all(bytes)?;
    temporary.as_file().sync_all()?;
    temporary
        .persist(path)
        .map_err(|error| error.error)?
        .sync_all()?;
    #[cfg(unix)]
    fs::File::open(parent)?.sync_all()?;
    Ok(())
}

pub fn load<T: DeserializeOwned + Serialize>(path: &Path) -> Result<Loaded<T>, String> {
    let _guard = WRITE_LOCK.lock().unwrap_or_else(|error| error.into_inner());
    let primary_error = match read(path) {
        Ok(value) => {
            return Ok(Loaded {
                value: Some(value),
                recovered: recovery_path(path)
                    .try_exists()
                    .map_err(|error| error.to_string())?,
            })
        }
        Err(error) => error,
    };
    let backup = backup_path(path);
    match read::<T>(&backup) {
        Ok(value) => {
            if primary_error.kind() != io::ErrorKind::NotFound && primary_error.kind() != io::ErrorKind::InvalidData {
                return Err(format!("Cannot read {}. Startup stopped to protect saved data ({primary_error}).", path.display()));
            }
            if primary_error.kind() == io::ErrorKind::InvalidData {
                let bytes = fs::read(path).map_err(|error| error.to_string())?;
                let mut preserved = tempfile::Builder::new()
                    .prefix(&format!("{}.corrupt-", path.file_name().unwrap_or_default().to_string_lossy()))
                    .tempfile_in(path.parent().unwrap())
                    .map_err(|error| error.to_string())?;
                preserved.write_all(&bytes).map_err(|error| error.to_string())?;
                preserved.as_file().sync_all().map_err(|error| error.to_string())?;
                preserved.keep().map_err(|error| error.to_string())?;
            }
            replace(&recovery_path(path), b"Automatic cleanup is disabled after backup recovery. Review and back up the data folder before removing this marker.\n")
                .map_err(|error| format!("Could not preserve recovery status: {error}"))?;
            let bytes = serde_json::to_vec_pretty(&value).map_err(|error| error.to_string())?;
            replace(path, &bytes).map_err(|error| format!("Could not restore {}: {error}", path.display()))?;
            log::warn!("Recovered {} from its last-good backup", path.display());
            Ok(Loaded { value: Some(value), recovered: true })
        }
        Err(backup_error) if primary_error.kind() == io::ErrorKind::NotFound && backup_error.kind() == io::ErrorKind::NotFound => {
            Ok(Loaded { value: None, recovered: recovery_path(path).try_exists().map_err(|error| error.to_string())? })
        }
        Err(_) => Err(format!("Cannot load {} or its backup. Startup stopped to protect settings and history. Restore the data folder from a backup; existing files have not been replaced.", path.display())),
    }
}

pub fn save<T: Serialize + DeserializeOwned>(path: &Path, value: &T) -> Result<(), String> {
    let bytes = serde_json::to_vec_pretty(value).map_err(|error| error.to_string())?;
    let _guard = WRITE_LOCK.lock().unwrap_or_else(|error| error.into_inner());
    match fs::read(path) {
        Ok(previous) => {
            serde_json::from_slice::<T>(&previous).map_err(|_| {
                format!(
                    "Refusing to overwrite unreadable {}. Restore it before saving.",
                    path.display()
                )
            })?;
            replace(&backup_path(path), &previous)
                .map_err(|error| format!("Backup failed: {error}"))?;
        }
        Err(error) if error.kind() == io::ErrorKind::NotFound => {}
        Err(error) => return Err(format!("Cannot preserve previous data: {error}")),
    }
    replace(path, &bytes).map_err(|error| format!("Atomic save failed: {error}"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::{json, Value};

    #[test]
    fn replacement_preserves_previous_valid_document() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("config.json");
        save(&path, &json!({"profile": "custom"})).unwrap();
        save(&path, &json!({"profile": "updated"})).unwrap();
        assert_eq!(read::<Value>(&path).unwrap()["profile"], "updated");
        assert_eq!(
            read::<Value>(&backup_path(&path)).unwrap()["profile"],
            "custom"
        );
    }

    #[test]
    fn truncated_primary_recovers_backup_and_preserves_damaged_bytes() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("history.json");
        save(&path, &json!({"entries": ["kept"]})).unwrap();
        save(&path, &json!({"entries": ["kept", "new"]})).unwrap();
        fs::write(&path, b"{\"entries\":").unwrap();
        let loaded = load::<Value>(&path).unwrap();
        assert!(loaded.recovered);
        assert_eq!(loaded.value.unwrap()["entries"], json!(["kept"]));
        assert_eq!(read::<Value>(&path).unwrap()["entries"], json!(["kept"]));
        assert!(load::<Value>(&path).unwrap().recovered);
        let preserved = fs::read_dir(directory.path())
            .unwrap()
            .map(|entry| entry.unwrap().path())
            .find(|entry| {
                entry
                    .file_name()
                    .unwrap()
                    .to_string_lossy()
                    .starts_with("history.json.corrupt-")
            })
            .unwrap();
        assert_eq!(fs::read(preserved).unwrap(), b"{\"entries\":");
    }

    #[test]
    fn invalid_primary_never_becomes_defaults_or_overwrites_backup() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("config.json");
        fs::write(&path, b"broken").unwrap();
        assert!(load::<Value>(&path).is_err());
        assert!(save(&path, &json!({"default": true})).is_err());
        assert_eq!(fs::read(path).unwrap(), b"broken");
    }

    #[test]
    fn missing_primary_recovers_backup_but_missing_both_is_fresh_install() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("config.json");
        assert!(load::<Value>(&path).unwrap().value.is_none());
        replace(&backup_path(&path), b"{\"custom\":true}").unwrap();
        let loaded = load::<Value>(&path).unwrap();
        assert!(loaded.recovered);
        assert_eq!(loaded.value.unwrap(), json!({"custom": true}));
    }

    #[test]
    fn failed_backup_leaves_primary_unchanged() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("config.json");
        save(&path, &json!({"custom": true})).unwrap();
        fs::create_dir(backup_path(&path)).unwrap();
        assert!(save(&path, &json!({"custom": false})).is_err());
        assert_eq!(read::<Value>(&path).unwrap(), json!({"custom": true}));
    }

    #[test]
    fn interrupted_temporary_write_does_not_change_primary_or_backup() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("config.json");
        save(&path, &json!({"profile": "first"})).unwrap();
        save(&path, &json!({"profile": "second"})).unwrap();
        let mut interrupted = tempfile::NamedTempFile::new_in(directory.path()).unwrap();
        interrupted.write_all(b"{\"profile\":").unwrap();
        interrupted.as_file().sync_all().unwrap();
        drop(interrupted);
        assert_eq!(
            load::<Value>(&path).unwrap().value.unwrap()["profile"],
            "second"
        );
        assert_eq!(
            read::<Value>(&backup_path(&path)).unwrap()["profile"],
            "first"
        );
    }

    #[test]
    fn invalid_backup_is_not_treated_as_a_fresh_install() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("history.json");
        fs::write(backup_path(&path), b"broken").unwrap();
        assert!(load::<Value>(&path).is_err());
        assert!(!path.exists());
    }

    #[test]
    fn real_settings_profiles_and_history_round_trip() {
        let directory = tempfile::tempdir().unwrap();
        let config_path = directory.path().join("config.json");
        let mut config = crate::config::AppConfig::default();
        config.tts.profiles[0].name = "Synthetic custom profile".into();
        config.playback.volume = 37;
        save(&config_path, &config).unwrap();
        let loaded = load::<crate::config::AppConfig>(&config_path)
            .unwrap()
            .value
            .unwrap();
        assert_eq!(loaded.tts.profiles[0].name, "Synthetic custom profile");
        assert_eq!(loaded.playback.volume, 37);
        let history_path = directory.path().join("history.json");
        let mut history = crate::history::HistoryLog::new();
        history.add(crate::history::create_entry(
            "Synthetic passage",
            "edge",
            "test",
            1.0,
        ));
        save(&history_path, &history).unwrap();
        let loaded = load::<crate::history::HistoryLog>(&history_path)
            .unwrap()
            .value
            .unwrap();
        assert_eq!(loaded.entries().len(), 1);
        assert_eq!(loaded.entries()[0].text, "Synthetic passage");
    }
}
