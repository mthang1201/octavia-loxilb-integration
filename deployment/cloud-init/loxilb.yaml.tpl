#cloud-config
hostname: loxilb-1
manage_etc_hosts: true
package_update: true
packages:
  - docker.io
write_files:
  - path: /etc/systemd/system/loxilb-container.service
    owner: root:root
    permissions: '0644'
    content: |
      [Unit]
      Description=LoxiLB standalone baseline container
      After=docker.service network-online.target
      Requires=docker.service
      Wants=network-online.target

      [Service]
      Environment=LOXILB_IMAGE={{LOXILB_IMAGE}}
      ExecStartPre=-/usr/bin/docker rm -f loxilb
      ExecStart=/usr/bin/docker run --name loxilb --privileged --network host --cap-add SYS_ADMIN -v /dev/log:/dev/log -v /var/lib/loxilb:/etc/loxilb ${LOXILB_IMAGE}
      ExecStop=/usr/bin/docker stop -t 20 loxilb
      Restart=always
      RestartSec=5

      [Install]
      WantedBy=multi-user.target
runcmd:
  - [mkdir, -p, /var/lib/loxilb]
  - [systemctl, daemon-reload]
  - [systemctl, enable, --now, loxilb-container.service]
final_message: "loxilb baseline container started"
