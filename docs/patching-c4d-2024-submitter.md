# Patching the C4D 2024 submitter

Copy the contents of [`C4D_2024/DeadlineRepository10`](../C4D_2024/DeadlineRepository10) over the
top of the matching folders in your Deadline repository.

Shout-out to Toms Seglins for the files.

## Additional steps

Cinema 4D can keep stale plugin paths that make Deadline report an error while still rendering in
some cases. To clear them:

1. Make a note of your additional plugin paths in the C4D preferences.
2. Close C4D and delete `plugins.json` (you can open this folder from the C4D preferences panel):

   ```
   C:\Users\<you>\AppData\Roaming\Maxon\Maxon Cinema 4D 2024_<hash>\plugins.json
   ```

3. Reopen C4D and set your plugin paths again.

If command-line renders fail on licensing, see
[Forcing command-line licences](forcing-command-line-licenses.md).

## Original download

The Notion page linked this zip; the same files are in the repo folder above.
[Deadline_C4D_2024_patch.zip (Dropbox)](https://www.dropbox.com/scl/fi/dqj8qjoenpebfn5ck12yb/Deadline_C4D_2024_patch.zip?rlkey=w40cky1xa2prtbxtetiuleag4&st=rt3h0oal&dl=0)
