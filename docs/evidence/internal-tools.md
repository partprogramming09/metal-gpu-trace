# Two tools the proofs mention

**Reader:** people reading a proof file who meet the names VegaFlow or WinBridge.

**In short:** both are the maintainer's own tools. You do not need either one to install or use metal-gpu-trace, and you cannot download them from this project.

- **VegaFlow** is a background program for Windows PCs with an AMD chip that has built-in graphics. It tunes the system while a game runs. metal-gpu-trace only reads a status file it leaves behind (the `device` block of a Windows summary) and never needs it; one reference run compares a game with and without it.
- **WinBridge** is a helper that runs a script on the maintainer's Windows PC from the Mac, so a release can be tried on real Windows hardware. The scripts it runs are in `windows/` in this repository. Where a proof says "a WinBridge job", read "a script run on a Windows PC".

To repeat a proof on your own machine you only need the command the proof lists; where it names one of these tools, the same recording works with any Windows PC and `perf_record`.
