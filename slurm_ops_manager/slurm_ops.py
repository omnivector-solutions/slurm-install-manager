#!/usr/bin/env python3
"""This module provides the SlurmManager."""
import logging
import subprocess
import tarfile
from pathlib import Path
from time import sleep

from ops.framework import (
    Object,
    StoredState,
)
from ops.model import ModelError
from slurm_ops_manager.slurm_ops_managers import (
    SlurmSnapManager,
    SlurmTarManager,
)
from slurm_ops_manager.utils import get_inventory


logger = logging.getLogger()


class SlurmManager(Object):
    """SlurmOpsManager."""

    _stored = StoredState()

    def __init__(self, charm, component):
        """Set the initial attribute values."""
        super().__init__(charm, component)

        self._charm = charm
        self._slurm_component = component

        self._stored.set_default(slurm_installed=False)
        self._stored.set_default(slurm_version_set=False)
        self._stored.set_default(resource_path=None)
        self._stored.set_default(resource_checked=False)

        if not self._stored.resource_checked:
            try:
                self._stored.resource_path = str(
                    self.model.resources.fetch('slurm')
                )
            except ModelError as e:
                logger.debug(e)
            self._stored.resource_checked = True

        logger.debug(
            "__init__(): self._stored.resource_path="
            f"{self._stored.resource_path}"
        )

        if self._stored.resource_path is not None:
            resource_size = Path(self._stored.resource_path).stat().st_size

            logger.debug(f'__init__(): resource_size={resource_size}')

            if resource_size > 0:
                if tarfile.is_tarfile(self._stored.resource_path):
                    logger.debug('__init__(): slurm resource is tar file.')
                    self._slurm_resource_manager = SlurmTarManager(
                        self._slurm_component,
                        self._stored.resource_path
                    )
                else:
                    logger.debug('__init__(): slurm resource is a snap file.')
                    self._slurm_resource_manager = SlurmSnapManager(
                        self._slurm_component,
                        self._stored.resource_path
                    )
            else:
                logger.debug('__init__(): slurm resource is a snap file.')

                self._slurm_resource_manager = SlurmSnapManager(
                    self._slurm_component,
                    self._stored.resource_path
                )
        else:
            logger.debug('__init__(): slurm resource from snapstore.')

            self._slurm_resource_manager = SlurmSnapManager(
                self._slurm_component,
                self._stored.resource_path
            )

    @property
    def hostname(self):
        """Return the hostname."""
        return self._slurm_resource_manager.hostname

    @property
    def port(self):
        """Return the port."""
        return self._slurm_resource_manager.port

    @property
    def inventory(self) -> str:
        """Return the node inventory and gpu count."""
        return get_inventory()

    @property
    def slurm_installed(self) -> bool:
        """Return the bool from the stored state."""
        return self._stored.slurm_installed

    @property
    def slurm_component(self) -> str:
        """Return the slurm component."""
        return self._slurm_resource_manager.slurm_component

    def get_munge_key(self) -> str:
        """Return the munge key."""
        return self._slurm_resource_manager.get_munge_key()

    def get_slurm_conf(self) -> str:
        """Return the slurm.conf."""
        return self._slurm_resource_manager.slurm_conf_path.read_text()

    def install(self) -> None:
        """Prepare the system for slurm."""
        # We need to ensure this function doesn't execute before
        # snapd is available. Wait on snapd here.
        # Need to make this a bit more robust in terms of eventually
        # erroring out if snapd never becomes available.
        while True:
            check = check_snapd()
            if check == 0:
                break
            sleep(1)

        self._slurm_resource_manager.setup_system()
        self._slurm_resource_manager.create_systemd_override_for_nofile()
        self._stored.slurm_installed = True

        # Set application version
        self._set_slurm_version()

    def upgrade(self, slurm_config=None) -> None:
        """Upgrade the slurm snap resource."""
        try:
            self._stored.resource_path = str(
                self.model.resources.fetch('slurm')
            )
        except ModelError as e:
            logger.debug(e)

        self._slurm_resource_manager.upgrade()

        if slurm_config is not None:
            self.render_slurm_configs()
            self.restart_slurm_component()

        # Set application version
        self._set_slurm_version()

    def configure_munge_key(self, munge_key):
        # self._slurm_resource_manager.configure_munge_key(munge_key)
        self._slurm_resource_manager.write_munge_key(munge_key)

    def configure_slurmctld_hostname(self, slurmctld_hostname):
        self._slurm_resource_manager.configure_slurmctld_hostname(
            slurmctld_hostname
        )

    def render_slurm_configs(self, slurm_config) -> None:
        """Render the slurm.conf and munge key, restart slurm and munge."""
        if not type(slurm_config) == dict:
            raise TypeError("Incorrect type for config.")

        # cgroup config will not always exist. We need to check for
        # cgroup_config and only write the cgroup.conf if
        # cgroup_config exists in the slurm_config object.
        if slurm_config.get('cgroup_config'):
            cgroup_config = slurm_config['cgroup_config']
            self._slurm_resource_manager.write_cgroup_conf(cgroup_config)

        # acct_gather config will not always exist. We need to check for
        # acct_gather and only write the acct_gather.conf if we have
        # acct_gather in the slurm_config object.
        if slurm_config.get('acct_gather'):
            self._slurm_resource_manager.write_acct_gather_conf(slurm_config)

        # Write slurm.conf and restart the slurm component.
        self._slurm_resource_manager.write_slurm_config(slurm_config)

    def _set_slurm_version(self):
        """Set the unit workload_version."""
        self._charm.unit.set_workload_version(
            self._slurm_resource_manager.slurm_version
        )

    def restart_slurm_component(self):
        """Restart slurm component."""
        self._slurm_resource_manager.restart_slurm_component()

    def scontrol(self, command):
        """Run scontrol."""
        self._slurm_resource_manager.scontrol("reconfigure")


def check_snapd():
    """Check to see if snapd is installed."""
    try:
        subprocess.check_call(
            ['snap', 'list'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT
        )
        return 0
    except subprocess.CalledProcessError as e:
        logger.debug(f"snapd error: {e}")
        return 1
