#!/usr/bin/env python3
"""This module provides the SlurmInstallManager."""
import logging
import subprocess
import sys
from pathlib import Path

from slurm_ops_manager.slurm_ops_base import SlurmOpsManagerBase


logger = logging.getLogger()


class SlurmSnapManager(SlurmOpsManagerBase):
    """Snap operations manager."""

    def __init__(self, component, resource_path):
        """Set initial attribute values."""
        super().__init__(component, resource_path)

    @property
    def _slurm_conf_dir(self) -> Path:
        return Path("/var/snap/slurm/common/etc/slurm")

    @property
    def _slurm_spool_dir(self) -> Path:
        return Path("/var/snap/slurm/common/var/lib/slurmd")

    @property
    def _slurm_state_dir(self) -> Path:
        return Path("/var/snap/slurm/common/var/spool/slurmd/")

    @property
    def _slurm_plugin_dir(self) -> Path:
        return Path("/snap/slurm/current/lib/slurm")

    @property
    def _slurm_log_dir(self) -> Path:
        return Path("/var/snap/slurm/common/var/log/slurm")

    @property
    def _slurm_pid_dir(self) -> Path:
        return Path("/tmp")

    @property
    def _mail_prog(self) -> Path:
        return Path("/snap/slurm/current/usr/bin/mail.mailutils")

    @property
    def _munge_key_path(self) -> Path:
        return Path("/var/snap/slurm/common/etc/munge/munge.key")

    @property
    def _slurm_plugstack_dir(self) -> Path:
        return Path("/var/snap/slurm/common/etc/slurm/plugstack.d")

    @property
    def _slurm_plugstack_conf(self) -> Path:
        return self._slurm_plugstack_dir / 'plugstack.conf'

    @property
    def _slurm_user(self) -> str:
        """Return the slurm user."""
        return "root"

    @property
    def _slurm_group(self) -> str:
        """Return the slurm group."""
        return "root"

    @property
    def _slurm_systemd_service(self) -> str:
        return f"snap.slurm.{self._slurm_component}"

    @property
    def _munge_socket(self) -> Path:
        """Return the munge socket."""
        return Path("/tmp/munged.socket.2")

    @property
    def _munged_systemd_service(self) -> str:
        return "snap.slurm.munged"

    @property
    def slurm_version(self) -> str:
        """Return slurm verion."""
        try:
            return subprocess.check_output([
                '/snap/bin/slurm.version']).decode().strip()
        except subprocess.CalledProcessError as e:
            print(f"Cannot get slurm version - {e}")
            sys.exit(-1)

    def _set_snap_mode(self):
        """Set the snap.mode."""
        try:
            subprocess.call([
                "snap",
                "set",
                "slurm",
                f"snap.mode={self._slurm_component}",
            ])
        except subprocess.CalledProcessError as e:
            print(f"Error setting snap.mode - {e}")

    def _install_slurm_snap_from_edge(self):
        try:
            subprocess.call([
                "snap",
                "install",
                "slurm",
                "--edge",
                "--classic",
            ])
        except subprocess.CalledProcessError as e:
            print(f"Error installing slurm snap - {e}")

    def upgrade(self):
        """Run upgrade operations."""
        # note: "snap refresh <foobar.snap>" does not work (it can
        # only refresh from the charm store (use "snap install"
        # instead).
        self.setup_system()

    def configure_munge_key(self, munge_key):
        """Configure the snap with the munge_key."""
        try:
            subprocess.call([
                "snap",
                "set",
                "munge",
                f"munge.key={munge_key}",
            ])
        except subprocess.CalledProcessError as e:
            print(f"Trouble setting the munge_key - {e}")

    def _provision_snap_systemd_service_override_file(self):
        override_dir = Path(
            f"/etc/systemd/system/snap.slurm.{self._slurm_component}.service.d"
        )
        if not override_dir.exists():
            override_dir.mkdir(parents=True)

        override_file = override_dir / 'override.conf'

        if override_file.exists():
            override_file.unlink()

        override_file.write_text(
            (self._template_dir / "systemd-override.conf").read_text()
        )

    def _systemctld_daemon_reload(self) -> None:
        try:
            subprocess.call([
                "systemctl",
                "daemon-reload",
            ])
        except subprocess.CalledProcessError as e:
            print(f"Error running daemon-reload - {e}")

    def setup_system(self) -> None:
        """Install the slurm snap, set the snap.mode, create the aliases."""
        # Install the slurm snap from the provided resource
        # if the resource file exists and its size is > 0, otherwise
        # install the snap from the snapstore.

        logger.debug(f'update_snap(): _resource_path={self._resource_path}')

        if self._resource_path is not None:
            resource_size = Path(self._resource_path).stat().st_size
            if resource_size > 0:
                logger.debug('update_snap(): running snap update')
                try:
                    subprocess.call([
                        "snap",
                        "install",
                        self._resource_path,
                        "--dangerous",
                        "--classic",
                    ])
                except subprocess.CalledProcessError as e:
                    print(f"Error installing slurm snap - {e}")

                # Create the aliases for the slurm cmds.
                # We only need to do this if we are installing from
                # a local resource.
                for cmd in self._slurm_cmds:
                    try:
                        subprocess.call([
                            "snap",
                            "alias",
                            f"slurm.{cmd}",
                            cmd,
                        ])
                    except subprocess.CalledProcessError as e:
                        print(f"Cannot create snap alias for: {cmd} - {e}")
            else:
                self._install_slurm_snap_from_edge()
        else:
            self._install_slurm_snap_from_edge()

        self._provision_snap_systemd_service_override_file()
        self._systemctld_daemon_reload()
        self._set_snap_mode()
