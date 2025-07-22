import logging
from enum import Enum
from shutil import which
from subprocess import CalledProcessError, check_call

logger = logging.getLogger(__name__)

JHACK_APP_NAME = "/snap/bin/jhack"


class JhackCommands(str, Enum):
    elect = "elect"


class JhackError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(self.message)


class JhackClient:
    def __init__(self, model: str, user: str):
        """Construct the JhackClient."""
        self.model = model
        self.user = user
        if not self._jhack_available():
            raise JhackError("Jhack executable not found. Please install Jhack!")

    def elect(self, application: str, unit_id: int):
        """Elect.

        Equivalent to `jhack utils elect <application>/<unit_id>` CLI command.

        Args:
            application (str): Name of the target application
            unit_id (int): ID of the unit to be elected as leader

        Raises:
            JhackError: Custom error raised when command fails
        """
        args = [JhackCommands.elect, f"{application}/{str(unit_id)}"]
        try:
            self._run_jhack_cmd("utils", *args)
        except CalledProcessError as e:
            raise JhackError(
                f"Error running `{JHACK_APP_NAME} {JhackCommands.elect}`"
            ) from e

    @staticmethod
    def _jhack_available() -> bool:
        """Check whether the Jhack executable is installed.

        Returns:
            bool: Whether the Jhack executable is installed
        """
        return which(JHACK_APP_NAME) is not None

    def _run_jhack_cmd(self, jhack_command: str, *args) -> int:
        """Run Jhack command.

        Args:
            jhack_command(str): Jhack command to execute
            args: List of arguments for the Jhack command

        Returns:
            int: Command's return code
        """
        logger.debug('Running: %s', " ".join([JHACK_APP_NAME, jhack_command, *args]))
        return check_call(
            [JHACK_APP_NAME, jhack_command, *args],
            env={
                "JUJU_MODEL": self.model,
                "USER": self.user,
                "JHACK_PROFILE": "devmode",
            }
        )
