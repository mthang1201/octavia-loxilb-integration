[[local|localrc]]

# Generated from lab/lab.env.  Do not edit the rendered local.conf or commit it.
HOST_IP={{HOST_IP}}
ADMIN_PASSWORD={{LAB_ADMIN_PASSWORD}}
DATABASE_PASSWORD={{LAB_DATABASE_PASSWORD}}
RABBIT_PASSWORD={{LAB_RABBIT_PASSWORD}}
SERVICE_PASSWORD={{LAB_SERVICE_PASSWORD}}
SERVICE_TOKEN={{LAB_SERVICE_TOKEN}}

GIT_BASE=https://opendev.org
GIT_BRANCH={{OPENSTACK_RELEASE}}
RECLONE=False

LOGFILE=$DEST/logs/stack.sh.log
LOGDAYS=7
VERBOSE=True
LOG_COLOR=False

# Keep this functional lab small.
disable_service cinder c-api c-vol c-sch
disable_service horizon
disable_service swift s-account s-container s-object s-proxy
disable_service tempest
disable_service heat h-api h-api-cfn h-api-cw h-eng

# Nova/KVM.  The host prerequisite check fails when /dev/kvm is unavailable.
VIRT_DRIVER=libvirt
LIBVIRT_TYPE=kvm
LIBVIRT_CPU_MODE=host-passthrough

# Neutron ML2/OVN from day one.
Q_AGENT=ovn
Q_ML2_PLUGIN_MECHANISM_DRIVERS=ovn
Q_ML2_PLUGIN_TYPE_DRIVERS=local,flat,vlan,geneve
Q_ML2_TENANT_NETWORK_TYPE=geneve
enable_plugin neutron https://opendev.org/openstack/neutron {{OPENSTACK_RELEASE}}
enable_service q-svc q-trunk q-qos
enable_service ovn-northd ovn-controller q-ovn-metadata-agent
disable_service q-agt q-l3 q-dhcp q-meta
ENABLE_CHASSIS_AS_GW=True

# Provider network through br-ex.  PUBLIC_INTERFACE is environment-specific.
Q_USE_PROVIDERNET_FOR_PUBLIC=True
OVN_L3_CREATE_PUBLIC_NETWORK=True
PUBLIC_INTERFACE={{PUBLIC_INTERFACE}}
PHYSICAL_NETWORK=public
OVS_PHYSICAL_BRIDGE=br-ex
FLOATING_RANGE={{PUBLIC_CIDR}}
PUBLIC_NETWORK_GATEWAY={{PUBLIC_GATEWAY}}
Q_FLOATING_ALLOCATION_POOL=start={{PUBLIC_POOL_START}},end={{PUBLIC_POOL_END}}
FIXED_RANGE=10.0.0.0/24
FIXED_NETWORK_SIZE=256

# Amphora reference provider.  The plugin creates the management network,
# certificates, keypair, small flavor and tagged Amphora image.
enable_plugin octavia https://opendev.org/openstack/octavia {{OCTAVIA_REF}}
enable_service octavia o-api o-cw o-hk o-hm o-da
OCTAVIA_NODE=standalone
OCTAVIA_LB_TOPOLOGY=SINGLE
OCTAVIA_MGMT_SUBNET={{OCTAVIA_MGMT_CIDR}}
OCTAVIA_MGMT_SUBNET_START={{OCTAVIA_MGMT_POOL_START}}
OCTAVIA_MGMT_SUBNET_END={{OCTAVIA_MGMT_POOL_END}}
OCTAVIA_HEALTH_KEY={{LAB_OCTAVIA_HEALTH_KEY}}
OCTAVIA_AMP_BASE_OS=ubuntu
OCTAVIA_AMP_DISTRIBUTION_RELEASE_ID=noble
OCTAVIA_AMP_IMAGE_SIZE=3
OCTAVIACLIENT_BRANCH={{OPENSTACK_RELEASE}}
OCTAVIA_LIB_BRANCH={{OPENSTACK_RELEASE}}
LIBS_FROM_GIT+=python-octaviaclient,

# Optional second L4 baseline; it must not block the Amphora/LoxiLB work.
enable_plugin ovn-octavia-provider https://opendev.org/openstack/ovn-octavia-provider {{OVN_OCTAVIA_PROVIDER_REF}}

[[post-config|$NOVA_CONF]]
[scheduler]
discover_hosts_in_cells_interval = 2
