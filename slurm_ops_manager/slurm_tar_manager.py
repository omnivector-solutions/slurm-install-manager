#!/usr/bin/env python3
"""This module provides the SlurmInstallManager."""
import logging
import os
import subprocess
import sys
from pathlib import Path
from time import sleep

from slurm_ops_manager.slurm_ops_base import SlurmOpsManagerBase


logger = logging.getLogger()


class SlurmTarManager(SlurmOpsManagerBase):
    """Operations for slurm tar resource."""

    _SLURM_SBIN_DIR = Path('/usr/local/sbin')
    _SLURM_SYSCONFIG_DIR = Path("/etc/sysconfig")

    _SLURM_UID = 990
    _SLURM_GID = 990

    _SLURM_TMP_RESOURCE = Path("/tmp/slurm-resource")

    def __init__(self, component, resource_path):
        """Set initial class attribute values."""
        super().__init__(component, resource_path)
        self._source_systemd_template = \
            self._template_dir / f'{self._slurm_component}.service'
        self._target_systemd_template = \
            Path(f'/etc/systemd/system/{self._slurm_component}.service')
        self._environment_file = \
            self._SLURM_SYSCONFIG_DIR / f'{self._slurm_component}'

    @property
    def _slurm_conf_dir(self) -> Path:
        return Path("/etc/slurm")

    @property
    def _slurm_spool_dir(self) -> Path:
        return Path("/var/spool/slurmd")

    @property
    def _slurm_state_dir(self) -> Path:
        return Path("/var/lib/slurmd")

    @property
    def _slurm_plugin_dir(self) -> Path:
        return Path("/usr/local/lib/slurm")

    @property
    def _slurm_log_dir(self) -> Path:
        return Path("/var/log/slurm")

    @property
    def _slurm_pid_dir(self) -> Path:
        return Path("/srv/slurm")

    @property
    def _slurm_plugstack_dir(self) -> Path:
        return Path("/etc/slurm/plugstack.d")

    @property
    def _slurm_plugstack_conf(self) -> Path:
        return self._slurm_plugstack_dir / 'plugstack.conf'

    @property
    def _mail_prog(self) -> Path:
        return Path("/usr/bin/mail")

    @property
    def _slurm_systemd_service(self) -> str:
        return self._slurm_component

    @property
    def _munge_key_path(self) -> str:
        return Path("/etc/munge/munge.key")

    @property
    def _munge_socket(self) -> Path:
        """Return the munge socket."""
        return Path("/var/run/munge/munge.socket.2")

    @property
    def _munged_systemd_service(self) -> str:
        return "munge"

    @property
    def _slurm_user(self) -> str:
        """Return the slurm user."""
        return "slurm"

    @property
    def _slurm_group(self) -> str:
        """Return the slurm group."""
        return "slurm"

    @property
    def slurm_version(self) -> str:
        """Return slurm verion."""
        os.environ['SLURM_CONF'] = str(self._slurm_conf_path)
        try:
            return subprocess.check_output(
                [self._slurm_component, "-V"]
            ).decode().strip().split()[1]
        except subprocess.CalledProcessError as e:
            print(f"Cannot get slurm version - {e}")
            sys.exit(-1)

    def upgrade(self):
        """Run upgrade operations."""
        self._provision_slurm_resource()

    def setup_system(self) -> None:
        """Prepare the system for slurm.

        * create slurm user/group
        * create filesystem for slurm
        * provision slurm resource
        """
        self._install_os_deps()
        self._create_slurm_user_and_group()
        self._prepare_filesystem()
        self._create_environment_files()

        self._provision_slurm_resource()

        self._set_ld_library_path()
        self._setup_systemd()

    def _install_os_deps(self) -> None:
        if self.os == 'ubuntu':
            try:
                subprocess.call([
                    'apt',
                    'install',
                    'libmunge2',
                    'libmysqlclient-dev',
                    'munge',
                    '-y',
                ])
            except subprocess.CalledProcessError as e:
                logger.debug(e)
        else:
            try:
                subprocess.call([
                    'yum',
                    'install',
                    '-y',
                    'mariadb-devel',
                    'munge',
                ])
            except subprocess.CalledProcessError as e:
                logger.debug(e)

        if not self._munge_key_path.exists():
            self._munge_key_path.write_bytes(os.urandom(1024))
            self._munge_key_path.chmod(0o400)

    def _create_slurm_user_and_group(self) -> None:
        """Create the slurm user and group."""
        try:
            subprocess.call([
                "groupadd",
                "-r",
                f"--gid={self._SLURM_GID}",
                self._slurm_user,
            ])
        except subprocess.CalledProcessError as e:
            logger.error(f"Error creating {self._slurm_group} - {e}")

        try:
            subprocess.call([
                "useradd",
                "-r",
                "-g",
                self._slurm_group,
                f"--uid={self._SLURM_UID}",
                self._slurm_user,
            ])
        except subprocess.CalledProcessError as e:
            logger.error(f"Error creating {self._slurm_user} - {e}")

    def _prepare_filesystem(self) -> None:
        """Create the needed system directories needed by slurm."""
        slurm_dirs = [
            self._slurm_plugstack_dir,
            self._slurm_conf_dir,
            self._slurm_log_dir,
            self._slurm_pid_dir,
            self._slurm_spool_dir,
            self._slurm_state_dir,
            self._SLURM_SYSCONFIG_DIR,
        ]
        for slurm_dir in slurm_dirs:
            slurm_dir.mkdir(parents=True, exist_ok=True)
            self._chown_slurm_user_and_group_recursive(str(slurm_dir))

        slurm_state_files = [
            "/var/lib/slurmd/node_state",
            "/var/lib/slurmd/front_end_state",
            "/var/lib/slurmd/job_state",
            "/var/lib/slurmd/resv_state",
            "/var/lib/slurmd/trigger_state",
            "/var/lib/slurmd/assoc_mgr_state",
            "/var/lib/slurmd/assoc_usage",
            "/var/lib/slurmd/qos_usage",
            "/var/lib/slurmd/fed_mgr_state",
        ]
        for slurmd_file in slurm_state_files:
            Path(slurmd_file).touch()
        self._chown_slurm_user_and_group_recursive('/var/lib/slurmd')

    def _chown_slurm_user_and_group_recursive(self, slurm_dir) -> None:
        """Recursively chown filesystem location to slurm user/slurm group."""
        try:
            subprocess.call([
                "chown",
                "-R",
                f"{self._slurm_user}:{self._slurm_group}",
                slurm_dir,
            ])
        except subprocess.CalledProcessError as e:
            logger.error(f"Error chowning {slurm_dir} - {e}")

    def _create_environment_files(self) -> None:
        slurm_conf = f"\nSLURM_CONF={str(self._slurm_conf_path)}\n"
        self._environment_file.write_text(slurm_conf)
        with open("/etc/environment", 'a') as f:
            f.write(slurm_conf)

    def _provision_slurm_resource(self) -> None:
        """Provision the slurm resource."""
        if not self._SLURM_TMP_RESOURCE.exists():
            self._SLURM_TMP_RESOURCE.mkdir(parents=True)

        try:
            subprocess.call([
                "tar",
                "-xzvf",
                self._resource_path,
                "-C",
                str(self._SLURM_TMP_RESOURCE),
            ])
        except subprocess.CalledProcessError as e:
            logger.error(f"Error untaring slurm bins - {e}")

        # Wait on the existence of slurmd bin to verify that the untaring
        # of the slurm.tar.gz resource has completed before moving on.
        while not Path(
           f"{str(self._SLURM_TMP_RESOURCE)}/sbin/slurmd").exists():
            sleep(1)

        for slurm_resource_dir in ['bin', 'sbin', 'lib', 'include']:
            cmd = (
                f"cp -R {str(self._SLURM_TMP_RESOURCE)}/"
                f"{slurm_resource_dir}/* /usr/local/{slurm_resource_dir}/"
            )
            try:
                subprocess.call(cmd, shell=True)
            except subprocess.CalledProcessError as e:
                logger.error(f"Error provisioning fs - {e}")

    def _set_ld_library_path(self) -> None:
        """Set the LD_LIBRARY_PATH."""
        Path('/etc/ld.so.conf.d/slurm.conf').write_text("/usr/local/lib/slurm")
        try:
            subprocess.call(["ldconfig"])
        except subprocess.CalledProcessError as e:
            logger.error(f"Error setting LD_LIBRARY_PATH - {e}")

    def _setup_systemd(self) -> None:
        """Preforms setup the systemd service."""
        try:
            subprocess.call([
                "cp",
                self._source_systemd_template,
                self._target_systemd_template
            ])
            subprocess.call([
                "systemctl",
                "daemon-reload",
            ])
            self._slurm_systemctl("enable")
        except subprocess.CalledProcessError as e:
            logger.error(f"Error setting up systemd - {e}")

    def configure_munge_key(self, munge_key):
        self._munge_key_path.write_text(munge_key)
