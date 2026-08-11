#cloud-config
hostname: {{INSTANCE_NAME}}
manage_etc_hosts: true
write_files:
  - path: /srv/lab-backend/index.html
    owner: root:root
    permissions: '0644'
    content: |
      {{INSTANCE_NAME}}
  - path: /etc/systemd/system/lab-backend.service
    owner: root:root
    permissions: '0644'
    content: |
      [Unit]
      Description=Baseline HTTP backend
      After=network-online.target
      Wants=network-online.target

      [Service]
      ExecStart=/usr/bin/python3 -m http.server 80 --directory /srv/lab-backend
      Restart=always
      RestartSec=2

      [Install]
      WantedBy=multi-user.target
runcmd:
  - [systemctl, daemon-reload]
  - [systemctl, enable, --now, lab-backend.service]
final_message: "baseline backend ready"
