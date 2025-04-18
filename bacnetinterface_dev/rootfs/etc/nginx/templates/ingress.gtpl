server {
    # listen on port
    listen 8099;
    {{if .port}}
        listen {{.port}};
    {{end}}


    allow 172.30.32.0/24;
    allow 127.0.0.0/24;

    {{ range .ip_array }}
        allow {{ . }};
    {{ end }}

    {{if not .accessible}}
        deny all;
    {{else}}
        allow all;
    {{end}}

    # forward request to backend
    location / {
        # send it to upstream
            
        # Replace header to true origin
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header x-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_pass http://127.0.0.1:7813;
    }

    # Serve static files
    location /static/ {
        root /usr/bin/;
        autoindex off;
        add_header Content-Type text/css;
    }

    location /ws {
        proxy_pass http://127.0.0.1:7813/ws;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header x-Forwarded-For $proxy_add_x_forwarded_for;
    }
}