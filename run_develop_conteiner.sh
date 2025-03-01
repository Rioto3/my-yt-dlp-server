# bin/sh
docker-compose -f docker-compose.develop.yml build --no-cache
docker-compose up -d

