# Hitman: Absolution – Contracts Mode Launcher

Bring Contracts mode back to life. Create contracts, save them, replay them and share them with other players, all from one simple launcher.

*Contracts mode by Dadmehr47*

## Features

- **Contracts mode works again**: create, save and replay your own contracts
- **Money**: earn money from every finished contract, or switch on **Unlimited money**
- **Share contracts online**: play contracts made by other players and let them play yours
- **Skip the game's own launcher** window with one switch
- **Built-in tutorial** that explains every option
- No addresses or config files to set up

## What you need

- Hitman: Absolution (Steam, Windows)
- The two hook files `dinput8.dll` and `hook.ini`.
- Download (Windows-x64.zip) from the https://github.com/LennardF1989/Hitman-5-Server/releases/tag/v1.2.2 of the original project and copy both `dinput8.dll` and `hook.ini` into your game folder (the one that contains `HMA.exe`).
- You do **not** need the original server program. This launcher replaces it.

## How to use

1. Download `Hitman-Absolution-Contracts-Launcher_v1.zip` from the **Releases** page and unzip it anywhere.
2. Run `Hitman-Absolution-Contracts-Launcher_v1.exe`. A short tutorial appears the first time.
3. Check the game folder. It is found automatically; if not, press **Browse** and pick the folder that contains `HMA.exe`.
4. Press **PLAY**, then choose **Contracts** in the game.

Keep the launcher window open while you play. It is the Contracts server, and closing it stops Contracts mode.

## Online sharing and privacy

Sharing is **off by default**. When you turn on **Share contracts online**, your contracts (with your Steam name and Steam ID) are sent to a shared server hosted on Cloudflare, and you receive contracts made by other players. You can turn it off at any time. Do not make contracts you do not want others to see.

## Troubleshooting

- **Windows SmartScreen or antivirus warning**: the app is a small Python program packaged with PyInstaller, which is sometimes flagged by mistake. The full source code is in this repository, so you can read it or build it yourself.
- **"Port 40147 is already in use"**: close the old `HM5.Server.exe` or another copy of the launcher.
- Contracts from other players arrive within about a minute. The very first sync can take longer.

## Build it yourself

Install Python 3, then run `build_exe.bat`. Your program appears in the `dist` folder. To run from source instead, use `start_launcher.bat`.

`hub.py` and `worker.js` are the sharing server (a Python version and a Cloudflare Workers version).

## Credits

- Original Hitman: Absolution server and hook: [[Hitman-5-Server by LennardF1989](https://github.com/LennardF1989/Hitman-5-Server)](https://github.com/LennardF1989/Hitman-5-Server) (AGPL-3.0 license)
- Launcher, contracts server and sharing server: Dadmehr47

## Disclaimer

Unofficial fan project. It is not affiliated with IO Interactive or Square Enix. Hitman is a trademark of its owners. No game files are included; you need your own copy of the game.
