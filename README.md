# deadline\_unofficial

Unofficially patched submissions scripts for Cinema4D \& Deadline



This is the official MographDotCom Slack (Thinkxbox Unofficial) repo for Deadline patched submission scripts to keep Deadline working with Maxon Cinema4D updates.

We may expand to include Houdini etc, but it is out of scope for the time being.



Simply copy the deadline folder for your C4D version and paste it over the top of the files in your repo.


+++ Android Deadline App Install ++

If you would like to install a basic Deadline Monitor on your Android, we now provide a legacy APK to do so.  To install this you will need to use ADB.  The quickest way to do this without the AndroidSDK (on Windows) is to use the super simple Universal ADB drivers, available from https://adb.clockworkmod.com/

Enable developer options on your android, disable both "verify apps over USB" and "verify bytecode of debuggable apps"

Once your phone is connected, tap the charging notification that says "charging this device via usb", then change the setting to "file transfer/android auto". You will need to reboot your phone if you are enabling developer options for the first time.  Then when you reconnect, you should be able to approve the ADB connection via the phone, with a checkbox to always accept your PC.



Now you can sideload the app using this command:
adb install --bypass-low-target-sdk-block Deadline\_Mobile\_1.2.apk



NOTE: You might need to point the terminal specifically to the adb.exe and the .apk file.





Associated Docs
Deadline support 2023.xx Submitter Fix
https://forums.thinkboxsoftware.com/t/cinema4d-2023-support/29670/8

Cinema4D 2023.2 Additional fix
https://forums.thinkboxsoftware.com/t/cinema4d-r2023-2-submission-error/30509

