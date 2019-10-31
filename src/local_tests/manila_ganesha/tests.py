#!/usr/bin/env python3

# Copyright 2019 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Encapsulate Manila Ganesha testing."""

import logging

from manilaclient import client as manilaclient

import zaza.model
import zaza.openstack.charm_tests.glance.setup as glance_setup
import zaza.openstack.charm_tests.neutron.tests as neutron_tests
import zaza.openstack.charm_tests.nova.utils as nova_utils
import zaza.openstack.charm_tests.test_utils as test_utils
import zaza.openstack.configure.guest as guest
import zaza.openstack.utilities.openstack as openstack_utils


class ManilaGaneshaTests(test_utils.OpenStackBaseTest):
    """Encapsulate Manila Ganesha tests."""
    RESOURCE_PREFIX = 'zaza-manilatests'

    @classmethod
    def setUpClass(cls):
        """Run class setup for running tests."""
        super(ManilaGaneshaTests, cls).setUpClass()
        cls.nova_client = (
            openstack_utils.get_nova_session_client(cls.keystone_session))
        cls.manila_client = manilaclient.Client(
            session=cls.keystone_session, client_version='2')


    def test_manila_share(self):
        """Test that Manila + Ganesha shares can be accessed on two instances.

        1. create a share
        2. Spawn two servers
        3. mount it on both
        4. write a file on one
        5. read it on the other
        6. profit
        """

        # Create Share
        share = self.manila_client.shares.create(
            share_type='cephfsnfstype', name='cephnfsshare1',
            share_proto="nfs", size=1)

        # Spawn Servers
        guest.launch_instance(
            glance_setup.LTS_IMAGE_NAME,
            vm_name='{}-ins-1'.format(self.RESOURCE_PREFIX))
        guest.launch_instance(
            glance_setup.LTS_IMAGE_NAME,
            vm_name='{}-ins-2'.format(self.RESOURCE_PREFIX))

        instance_1 = self.nova_client.servers.find(
            name='{}-ins-1'.format(self.RESOURCE_PREFIX))
        fip_1 = neutron_tests.floating_ips_from_instance(instance_1)[0]
        instance_2 = self.nova_client.servers.find(
            name='{}-ins-2'.format(self.RESOURCE_PREFIX))
        fip_2 = neutron_tests.floating_ips_from_instance(instance_2)[0]

        share.allow(access_type='ip', access=fip_1, access_level='rw')
        share.allow(access_type='ip', access=fip_2, access_level='rw')

        # Mount Share

        username = guest.boot_tests['bionic']['username']
        password = guest.boot_tests['bionic'].get('password')
        privkey = openstack_utils.get_private_key(nova_utils.KEYPAIR_NAME)
        mount_path = share.export_locations[0]

        # Write a file on instance_1

        def verify_setup(stdin, stdout, stderr):
            status = stdout.channel.recv_exit_status()
            self.assertEqual(status, 0)

        openstack_utils.ssh_command(
            username, fip_1, 'instance-1',
            'sudo apt install -yq nfs-common && '
            'sudo mkdir -p /mnt/ceph && '
            'sudo mount -t nfs -o nfsvers=4.1,proto=tcp {} /mnt/ceph && '
            'echo "test" | sudo tee /mnt/ceph/test'.format(
                mount_path),
            password=password, privkey=privkey, verify=verify_setup)

        openstack_utils.ssh_command(
            username, fip_2, 'instance-2',
            'sudo apt install -yq nfs-common && '
            'sudo /bin/mkdir -p /mnt/ceph && '
            'sudo /bin/mount -t nfs -o nfsvers=4.1,proto=tcp {} /mnt/ceph'
                .format(mount_path),
            password=password, privkey=privkey, verify=verify_setup)

        def verify(stdin, stdout, stderr):
            status = stdout.channel.recv_exit_status()
            out = ""
            print("[{}] Stdout:".format(status))
            for line in iter(stdout.readline, ""):
                out += line
            self.assertEqual(out, "test\n")

        # Read that file on instance_2

        openstack_utils.ssh_command(
            username, fip_2, 'instance-2',
            'sudo cat /mnt/ceph/test'.format(
                mount_path),
            password=password, privkey=privkey, verify=verify)


