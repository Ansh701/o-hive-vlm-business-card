#!/usr/bin/env bash
set -Eeuo pipefail

exec > >(tee /var/log/o-hive-cpu-benchmark.log /dev/console) 2>&1

finish() {
  status=$?
  if [ "$status" -ne 0 ]; then
    echo "O_HIVE_CPU_BENCHMARK_FAILED status=$status"
    tail -n 120 /var/log/o-hive-cpu-benchmark-detail.log 2>/dev/null || true
    {
      echo "status=failed exit_code=$status"
      tail -c 2600 /var/log/o-hive-cpu-benchmark-detail.log 2>/dev/null || true
    } >/tmp/o-hive-publish.log
  else
    cp /tmp/o-hive-cpu-result.log /tmp/o-hive-publish.log
  fi
  result="$(base64 -w0 /tmp/o-hive-publish.log | head -c 3800)"
  aws ssm put-parameter \
    --region us-east-1 \
    --name /o-hive/benchmark/cpu-result \
    --type String \
    --value "$result" \
    --overwrite >/dev/null 2>&1 || true
  shutdown -h now
}
trap finish EXIT

echo "O_HIVE_CPU_BENCHMARK_STAGE=bootstrap"
dnf install -y -q docker git >/var/log/o-hive-cpu-benchmark-detail.log 2>&1
systemctl enable --now docker >>/var/log/o-hive-cpu-benchmark-detail.log 2>&1

echo "O_HIVE_CPU_BENCHMARK_STAGE=checkout"
git clone --quiet https://github.com/Ansh701/o-hive-vlm-business-card.git /opt/o-hive
git -C /opt/o-hive checkout --quiet fbfa0562a4e5842b991442c90ae28a04601f2051
mkdir -p /opt/model-cache

echo "O_HIVE_CPU_BENCHMARK_STAGE=runtime"
docker pull pytorch/pytorch:2.14.0-cuda12.6-cudnn9-runtime@sha256:a77983eb7a3042ccf41a94da547a7f54a47fb70da15c36d67a8e8a329ebaa098 \
  >>/var/log/o-hive-cpu-benchmark-detail.log 2>&1

echo "O_HIVE_CPU_BENCHMARK_STAGE=model"
docker run --rm \
  --volume /opt/o-hive:/workspace:ro \
  --volume /opt/model-cache:/opt/model-cache \
  --workdir /workspace \
  --env HF_HOME=/opt/model-cache \
  pytorch/pytorch:2.14.0-cuda12.6-cudnn9-runtime@sha256:a77983eb7a3042ccf41a94da547a7f54a47fb70da15c36d67a8e8a329ebaa098 \
  bash -lc 'python -m pip install --quiet --break-system-packages --no-cache-dir -r inference/requirements.txt && python scripts/benchmark_model_cpu.py --threads 4 --dtype bfloat16' \
  >/tmp/o-hive-cpu-result.log 2>/var/log/o-hive-cpu-benchmark-detail.log

cat /tmp/o-hive-cpu-result.log
echo "O_HIVE_CPU_BENCHMARK_COMPLETE"
