from shutil import which
import json
import logging
import os
import subprocess
import sys

import c4d


def get_deadlinecommand():
    """
    Finds the Deadline Command executable as it is installed on your machine by searching in the following order:
    * The DEADLINE_PATH environment variable
    * The PATH environment variable
    * The file /Users/Shared/Thinkbox/DEADLINE_PATH
    """

    for env in ("DEADLINE_PATH", "PATH"):
        try:
            env_value = os.environ[env]
        except KeyError:
            # if the error is a key error it means that DEADLINE_PATH is not set.
            # however Deadline command may be in the PATH or on OSX it could be in the file /Users/Shared/Thinkbox/DEADLINE_PATH
            continue

        exe = which("deadlinecommand", path=env_value)
        if exe:
            return exe

    # On OSX, we look for the DEADLINE_PATH file if the environment variable does not exist.
    if os.path.exists("/Users/Shared/Thinkbox/DEADLINE_PATH"):
        with open("/Users/Shared/Thinkbox/DEADLINE_PATH") as dl_file:
            deadline_bin = dl_file.read().strip()
        exe = which("deadlinecommand", path=deadline_bin)
        if exe:
            return exe

    raise Exception("Deadline could not be found.  Please ensure that Deadline is installed.")


def call_deadlinecommand(arguments, format_output_as_json=False):
    """
    Calls DeadlineCommand with a given list of arguments.
    If json_output is true the output is returned as a json dictionary.
    Otherwise the raw string is output is returned.
    """
    command = [get_deadlinecommand()]
    if format_output_as_json:
        # JSON formatting option must come directly after the Deadline Command executable in the argument list.
        command.append('-prettyJSON')
    command.extend(arguments)

    proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, _ = proc.communicate()

    if format_output_as_json:
        json_out = json.loads(output)
        if json_out["ok"]:
            return json_out["result"]
        else:
            raise Exception(json_out["result"])
    else:
        if proc.returncode:
            raise Exception(output)
        return output


def GetC4DSubmissionDir():
    json_out = call_deadlinecommand(["-GetRepositoryPath", "submission/Cinema4D/Main"], format_output_as_json=True )
    return json_out.replace( "\\", "/" )


def main():
    # Get the repository path
    try:
        submissionDir = GetC4DSubmissionDir()
    except Exception as e:
        print("Error:Failed to pull Deadline Integrated submitter: %s" % e)
        raise
    
    if submissionDir not in sys.path:
        print( 'Appending "%s" to system path to import SubmitC4DToDeadline module' % submissionDir )
        sys.path.append( submissionDir )
    else:
        print( '"%s" is already in the system path' % submissionDir )
    
    try:
        import SubmitC4DToDeadline
    except ImportError as e:
        print("Error: Failed to import Deadline: %s" % e)
        raise
    
    SubmitC4DToDeadline.main( submissionDir )


if __name__=='__main__':
    main()
