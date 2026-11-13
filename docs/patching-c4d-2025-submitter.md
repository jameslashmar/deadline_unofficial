# Patching the C4D 2025 submitter

Copy the contents of [`C4D_2025.1.0/DeadlineRepository10`](../C4D_2025.1.0/DeadlineRepository10)
over the top of the matching folders in your Deadline repository. The scripts are based on
Deadline 10.4.0.10.

Shout-out to Toms Seglins for the files.

> [!NOTE]
> This patch was marked experimental on the original Notion page.

## Additional steps

Cinema 4D can keep stale plugin paths that make Deadline report an error while still rendering in
some cases. To clear them:

1. Make a note of your additional plugin paths in the C4D preferences.
2. Close C4D and delete `plugins.json` (you can open this folder from the C4D preferences panel):

   ```
   C:\Users\<you>\AppData\Roaming\Maxon\Maxon Cinema 4D 2025_<hash>\plugins.json
   ```

3. Reopen C4D and set your plugin paths again.

## Original download

The Notion page linked this zip; check it against the repo folder above before relying on it.
[Deadline_C4D_R2025_patch_experimental.zip (Dropbox)](https://www.dropbox.com/scl/fi/9m9njhajlz6qspuokvr4q/Deadline_C4D_R2025_patch_experimental.zip?rlkey=32urej2rm70tvjj0qkhu0f5b5&st=odwkjjfv&dl=0)
