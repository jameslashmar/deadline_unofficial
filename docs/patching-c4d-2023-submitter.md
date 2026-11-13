# Patching the C4D 2023 submitter

Copy the contents of [`C4D_2023/DeadlineRepository10`](../C4D_2023/DeadlineRepository10) over the
top of the matching folders in your Deadline repository.

Shout-out to Toms Seglins for the files.

## Additional steps

Cinema 4D can keep stale plugin paths that make Deadline report an error while still rendering in
some cases. To clear them:

1. Make a note of your additional plugin paths in the C4D preferences.
2. Close C4D and delete `plugins.json` (you can open this folder from the C4D preferences panel):

   ```
   C:\Users\<you>\AppData\Roaming\Maxon\Maxon Cinema 4D 2023_<hash>\plugins.json
   ```

3. Reopen C4D and set your plugin paths again.

> [!WARNING]
> Do not downgrade 2023.2 to 2023.1.3. Uninstall, clear the preferences folder
> (`%APPDATA%\Maxon\Maxon Cinema 4D 2023_<hash>`), then install 2023.1.3 from scratch.

## Associated docs

- [Deadline support for 2023.x: submitter fix](https://forums.thinkboxsoftware.com/t/cinema4d-2023-support/29670/8)
- [Cinema 4D 2023.2: additional fix](https://forums.thinkboxsoftware.com/t/cinema4d-r2023-2-submission-error/30509)

## Original download

The Notion page linked this zip; the same files are in the repo folder above.
[2023 Submitter.zip (Dropbox)](https://www.dropbox.com/s/l47bnw8znyd65y2/2023%20Submitter.zip?dl=0)
