# Self-host SelfX

SelfX runs as a native service on Ubuntu 24.04. On Windows, use Ubuntu 24.04 in WSL2 and start SelfX automatically at sign-in. The CPU setup gives you manual tools, workflows, and local Whisper transcription. Add an Ollama model when you want to plan workflows from prompts.

You need an internet connection for the installation and the first download of each model. Keep enough disk space for the packages, model downloads, and both the input and output of your largest jobs.

## Ubuntu 24.04

Use an Ubuntu 24.04 system on 64-bit x86 or ARM with systemd, an administrator account with `sudo` access, and Git. If Git is missing, run `sudo apt update` followed by `sudo apt install git`.

```sh
git clone https://github.com/DrvDispatch/SelfX.git selfx
cd selfx
sudo bash deploy/install.sh --port 8800
```

The installer builds the web app, sets up the database and background workers, and enables SelfX at boot. Use a different available `--port` from `1024` to `65535` if `8800` is busy. The default listener is `127.0.0.1`, so SelfX is reachable only from the host. For a server, use the [private VPS access guide](../deploy/vps.md) to open SelfX from your own computer.

## Windows with WSL2

If needed, install Ubuntu 24.04 from an administrator PowerShell window. Restart Windows if prompted. Launch the distribution once to create your Linux account and password. Run the SelfX setup from the Windows account that will use SelfX. [Microsoft WSL installation guide](https://learn.microsoft.com/en-us/windows/wsl/install)

```powershell
wsl.exe --install -d Ubuntu-24.04
wsl.exe --list --verbose
wsl.exe -d Ubuntu-24.04 -- ps -p 1 -o comm=
```

The distribution should show WSL version `2`, and `ps` should print `systemd`. If the distribution shows version `1`, run `wsl.exe --set-version Ubuntu-24.04 2`. If systemd is inactive, open Ubuntu, edit `/etc/wsl.conf` with `sudo`, and set `systemd=true` under `[boot]`. Save your Linux work before running `wsl.exe --terminate Ubuntu-24.04` from PowerShell. Relaunch Ubuntu and check again. [Microsoft systemd guide](https://learn.microsoft.com/en-us/windows/wsl/systemd)

With Git for Windows installed, open PowerShell and run these commands. If you downloaded and extracted a GitHub source archive, start in its `SelfX` directory and run the last command.

```powershell
git clone https://github.com/DrvDispatch/SelfX.git selfx
Set-Location selfx
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\deploy\setup-windows.ps1 -Port 8800
```

The wrapper runs the native installer inside Ubuntu, then creates and starts the `SelfX WSL - Ubuntu-24.04` scheduled task for your Windows account. This task keeps WSL running while you are signed in, including when terminal windows are closed. After a Windows restart, sign in to start SelfX. If you installed Ubuntu 24.04 under a different WSL name, add `-Distro YourDistroName` and substitute that name in subsequent WSL commands and the task name. [Microsoft WSL networking guide](https://learn.microsoft.com/en-us/windows/wsl/networking)

## First sign-in

Open [http://127.0.0.1:8800](http://127.0.0.1:8800) on the machine running SelfX. Substitute the port you chose. Sign in as `admin` with the password generated during setup. To retrieve it, run the following on Ubuntu. On Windows, first enter Ubuntu with `wsl.exe -d Ubuntu-24.04`.

```sh
sudo sed -n 's/^SELFX_ADMIN_PASSWORD=//p' /etc/selfx/selfx.env
```

The environment file also contains service credentials. Keep it private. The bootstrap password only applies when SelfX creates the first user. Changing that environment variable later leaves the account’s existing password in place.

Try a small job from **Tools**. To test speech-to-text, upload a short clip to **Transcribe audio / video**. The first transcription can take longer while Whisper downloads its model. Open **Activity** for the job’s state and results. Download outputs you want to keep. By default, SelfX cleans up retained job files after 24 hours.

## Local models

### Whisper transcription

The native setup uses the `small` faster-whisper model with CPU inference in `int8`. In `/etc/selfx/selfx.env`, set `WHISPER_MODEL=base` or `WHISPER_MODEL=tiny` for a smaller default on a slower host. Run a short transcription in SelfX to cache the model under `/var/lib/selfx/huggingface`. To use the cached models without network downloads, set `WHISPER_LOCAL_ONLY=true` after the initial download. Choose larger models when a trial on your own audio shows that the extra processing time is worthwhile. [faster-whisper](https://github.com/SYSTRAN/faster-whisper)

### Qwen workflow planning

Install Ollama in the same Ubuntu environment as SelfX, including when using WSL. With Ollama running locally, check that its model API responds and pull a starter model. [Ollama Linux setup](https://docs.ollama.com/linux), [Qwen3.5 model tags](https://ollama.com/library/qwen3.5/tags)

```sh
curl -fsS http://127.0.0.1:11434/api/tags
ollama pull qwen3.5:4b
sudoedit /etc/selfx/selfx.env
```

Set these values in the environment file and restart the SelfX services. Open **Create**, enter a request, and review the proposed steps before running them.

```dotenv
OLLAMA_URL=http://127.0.0.1:11434
SELFX_PLANNER_MODEL=qwen3.5:4b
SELFX_PLANNER_NUM_CTX=8192
```

If the host struggles with that model, try `qwen3.5:2b` and `4096` context tokens, or use manual tools and recipes. **AI models → Hardware check** shows what the API host can see. Use those estimates to pick an initial profile. Measure memory and planning speed with your own prompts on the model host before increasing the model size or trying longer context windows such as 32K or 128K.

## Manage the services

Run the following commands on Ubuntu. On Windows, open the Ubuntu distribution with `wsl.exe -d Ubuntu-24.04` first. Wait until current jobs finish before taking workers offline.

```sh
sudo systemctl stop selfx-api selfx-worker@default selfx-worker@heavy
sudo systemctl start selfx-api selfx-worker@default selfx-worker@heavy
```

Apply settings changes with a restart.

```sh
sudo systemctl restart selfx-api selfx-worker@default selfx-worker@heavy
```

To change the port, rerun the installer with the new `--port`. On Windows, rerun the wrapper with the new `-Port`. Use the new port in browser bookmarks, health checks, and tunnels.

On Windows, inspect the sign-in task with `Get-ScheduledTask -TaskName 'SelfX WSL - Ubuntu-24.04'`. Disable future sign-in launches with `Disable-ScheduledTask -TaskName 'SelfX WSL - Ubuntu-24.04'`. Use `Enable-ScheduledTask` with the same name to restore sign-in launches. Stop SelfX inside Ubuntu before stopping WSL.

### Service checks

Use your configured port in the first command. The PostgreSQL and Redis connectivity check returns `{"status":"ok","service":"selfx"}`. If jobs appear stuck, check both worker units and their recent logs as well.

```sh
curl -fsS http://127.0.0.1:8800/api/v1/healthz
sudo systemctl status selfx-api selfx-worker@default selfx-worker@heavy selfx-redis postgresql
sudo journalctl -u selfx-api -u selfx-worker@default -u selfx-worker@heavy -u selfx-redis -n 100 --no-pager
df -h /var/lib/selfx
```

- **Windows reports the port is already in use.** Run `Get-NetTCPConnection -LocalPort 8800 -State Listen` in PowerShell with the selected port to see which process has a listener. Run the setup again with a free port using `-Port`.
- **The Windows browser can’t connect.** Check the health URL inside Ubuntu first, then run `Invoke-RestMethod http://127.0.0.1:8800/api/v1/healthz` in PowerShell. If Ubuntu responds but Windows does not return the SelfX health fields, check the scheduled task and WSL localhost forwarding. [Microsoft WSL networking guide](https://learn.microsoft.com/en-us/windows/wsl/networking)
- **A job is waiting.** Check that both worker units are running, then look for a busy queue, insufficient disk space, or a failed tool in the logs. Open **Activity** to see the status and workflow step.
- **Transcription fails during model load.** Check available space and try a smaller model. If you enabled `WHISPER_LOCAL_ONLY`, cache the selected model first.
- **Prompt planning is unavailable.** Run `ollama list` in Ubuntu and check that the configured tag is present. If the Ollama API responds, use a smaller model or context and try again.

## Update SelfX

From the Git checkout, review the changes for the version you are installing and take a backup. Wait for jobs to finish before updating.

```sh
git pull --ff-only
sudo bash deploy/install.sh
```

The native installer keeps the existing configuration, data, and port unless you pass new settings. On Windows, pull the changes in PowerShell and rerun `setup-windows.ps1`. Include `-Distro` if you used a custom distribution name. Check the health endpoint and complete a small job after updating.

## Back up and restore

Run these commands in Ubuntu, including on Windows. They target the installer’s PostgreSQL cluster `16/main` and the default data paths. Export important recipes from **Recipes** separately. The browser stores those recipes per account, so include the exported JSON files in your backup and import them on the new browser or origin. [Ubuntu PostgreSQL client commands](https://manpages.ubuntu.com/manpages/noble/man1/pg_wrapper.1.html)

### Backup

Wait for running and queued work to finish. Stop the API and both workers before stopping Redis so that the database and file backups represent the same idle state. This makes SelfX unavailable until you restart it.

```sh
umask 077
backup=$(mktemp -d "$HOME/selfx-backup.XXXXXX")
sudo systemctl stop selfx-api selfx-worker@default selfx-worker@heavy
sudo systemctl stop selfx-redis
sudo -u postgres pg_dump --cluster 16/main --format=custom selfx > "$backup/selfx.dump"
sudo tar -C / -czf - etc/selfx/selfx.env var/lib/selfx/data var/lib/selfx/redis > "$backup/state.tar.gz"
sudo systemctl start selfx-redis
sudo systemctl start selfx-api selfx-worker@default selfx-worker@heavy
```

Check that both backup commands succeeded, then run `pg_restore --list "$backup/selfx.dump"` and `tar -tzf "$backup/state.tar.gz"` to verify that the archive contents can be listed. Store the backup directory securely outside the machine. The archives contain private files, account data, and service credentials. The Whisper cache and Ollama models can be downloaded again. Save the caches separately if your recovery host needs to operate offline. [PostgreSQL backup formats](https://www.postgresql.org/docs/16/app-pgdump.html)

### Restore to a fresh host

Use archives you created and trust. Install the same SelfX version on the new host first. Keep that host private and unused by other people while you restore. Copy the backup directory to Ubuntu and set `backup` to its location.

```sh
backup=/path/to/selfx-backup
sudo systemctl stop selfx-api selfx-worker@default selfx-worker@heavy
sudo systemctl stop selfx-redis
sudo -u postgres createdb --cluster 16/main --owner=selfx selfx_recovered
sudo -u postgres pg_restore --cluster 16/main --single-transaction --dbname=selfx_recovered < "$backup/selfx.dump"
```

Continue only after the database import succeeds. The two database renames preserve the fresh installer database as `selfx_before_restore` and switch the recovered database into its place.

```sh
sudo -u postgres psql --cluster 16/main --set=ON_ERROR_STOP=1 --single-transaction --dbname=postgres \
  --command='ALTER DATABASE selfx RENAME TO selfx_before_restore' \
  --command='ALTER DATABASE selfx_recovered RENAME TO selfx'
sudo tar -C / -xzf "$backup/state.tar.gz" --no-same-owner \
  var/lib/selfx/data var/lib/selfx/redis
sudo chown -R selfx:selfx /var/lib/selfx/data /var/lib/selfx/redis
```

Keep the fresh host’s generated service credentials and reapply any custom model, retention, or limit settings from the saved environment file. If a file in the backup is already past its original expiry, recover it from the archive before starting SelfX and its cleanup task. [PostgreSQL restore options](https://www.postgresql.org/docs/16/app-pgrestore.html)

```sh
sudo systemctl start selfx-redis
sudo systemctl start selfx-api selfx-worker@default selfx-worker@heavy
```

Check health, sign in with your account from the source backup, and open a restored workflow or result. Import your exported recipes in the browser.
