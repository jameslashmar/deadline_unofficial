# deadline\_unofficial

## Unofficially patched submissions scripts for Cinema4D & Deadline



This is the official MographDotCom Slack (Thinkxbox Unofficial) repo for Deadline patched submission scripts to keep Deadline working with Maxon Cinema4D updates.

We may expand to include Houdini etc, but it is out of scope for the time being.



Simply copy the deadline folder for your C4D version and paste it over the top of the files in your repo.

## Supported versions

| Folder | Cinema 4D | Notes |
|---|---|---|
| `C4D_2023` | 2023.x | |
| `C4D_2024` | 2024.x | |
| `C4D_2025.1.0` | 2025.x | |
| `C4D_2026` | 2026.x | Based on Deadline 10.4.2.2. Clay render / bake view transform fixes |
| `C4D_2027` | 2027.x | As 2026, plus 2027 render executables and a submitter with a menu icon |

Each folder's `info.txt` has version-specific install notes.

## C4D submitter client (2026+)

From 2026 the C4D side needs the `DeadlineC4DClient.pyp` launcher copied manually from
`DeadlineRepository10\submission\Cinema4D\Client` into your Cinema 4D `plugins` folder
(e.g. `C:\Program Files\Maxon Cinema 4D 2027\plugins`, admin rights required).

In `C4D_2027` the launcher also gives the **Submit To Deadline** command an icon. Copy
`Thinkbox-Deadline-01.png` into the same `plugins` folder alongside the `.pyp`. If the icon
is missing the submitter still loads, just without the icon. Any load problems are logged to
`DeadlineC4DClient_error.log` next to the plugin.


## Android Deadline App Install

If you would like to install a basic Deadline Monitor on your Android, we now provide a legacy APK to do so.

To install this you will need to use ADB.  The quickest way to do this without the AndroidSDK (on Windows) is to use the super simple Universal ADB drivers, available from https://adb.clockworkmod.com/

Enable developer options on your android, disable both ```verify apps over USB``` and ```verify bytecode of debuggable apps```.

Once your phone is connected, tap the charging notification that says ```charging this device via usb```, then change the setting to ```file transfer/android auto```. You will need to reboot your phone if you are enabling developer options for the first time.  Then when you reconnect, you should be able to approve the ADB connection via the phone, with a checkbox to always accept your PC.

Now you can sideload the app using this command:

```adb install --bypass-low-target-sdk-block Deadline_Mobile_1.2.apk```

**NOTE:** You might need to point the terminal specifically to the adb.exe and the .apk file.




## Guides and resources

The guides from the old Notion wiki now live in [`docs/`](docs/README.md): patching each C4D
submitter, forcing command-line licences, rendering a frame per GPU, usage-based licensing
(UBL), After Effects farm settings and the Unreal Engine 5.3 submitter.

## Associated Docs
Deadline support 2023.xx Submitter Fix

https://forums.thinkboxsoftware.com/t/cinema4d-2023-support/29670/8

Cinema4D 2023.2 Additional fix

https://forums.thinkboxsoftware.com/t/cinema4d-r2023-2-submission-error/30509


#