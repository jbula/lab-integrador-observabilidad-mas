# OTel Collector para ECS/ECR — config horneada (sin EFS)
FROM otel/opentelemetry-collector-contrib:0.103.0

COPY collector-config.aws.yaml   /etc/otel/collector-config.aws.yaml
COPY collector-config.local.yaml /etc/otel/collector-config.local.yaml

# Por defecto arranca con la config AWS (en ECS se puede sobreescribir con 'command')
CMD ["--config=/etc/otel/collector-config.aws.yaml"]
