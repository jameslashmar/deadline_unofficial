# Forcing command-line licences (C4D 2024)

Maxon added a flag for Commandline in C4D 2024 that lets it use the Maxon Account licence type
without error. This should stop the recurring command-line licence errors on render nodes.

```ini
g_hideaccountmode=false
```

Add the line to `config.txt` in the C4D resource folder:

```
C:\Program Files\Maxon Cinema 4D 2024\resource\config.txt
```

> [!TIP]
> If a machine is both a workstation and a render node, put the flag in
> `config.commandline.txt` (same folder) instead. C4D itself keeps using the Maxon App licence
> while Commandline uses the Maxon Account.

If you have already customised either config file, add the line by hand rather than replacing the
file.
