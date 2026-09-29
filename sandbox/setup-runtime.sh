#!/bin/sh
# 以 root 身份安装到 Debian Python sandbox。必须由操作人员明确选择已有的
# sandbox ID；此脚本不会替换已有 sandbox。
# 可选的第一个参数：包含已验证 Debian 软件包和 wheel 的目录。
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo 'Runtime installation requires root.' >&2
    exit 1
fi

export DEBIAN_FRONTEND=noninteractive
offline_dir=${1:-}
if [ -n "$offline_dir" ] && [ -d "$offline_dir" ]; then
    # 软件包不完整时直接失败，不要静默尝试访问网络。
    dpkg --install "$offline_dir"/*.deb
    apt-get check
else
    apt-get -o Acquire::Retries=2 -o Acquire::http::Timeout=30 update
    apt-get -o Acquire::Retries=2 -o Acquire::http::Timeout=30 install -y --no-install-recommends \
        golang-go default-jdk-headless nodejs npm
fi

# 官方镜像使用 /usr/local 下的 Python，因此 Debian 的 python3-yaml 会安装到
# 另一个解释器中。技能辅助依赖需要在这里安装。
if ! python -c 'import yaml' 2>/dev/null; then
    if [ -n "$offline_dir" ] && [ -d "$offline_dir" ]; then
        python -m pip install --no-cache-dir --no-index --find-links "$offline_dir" 'PyYAML==6.0.3'
    else
        python -m pip install --no-cache-dir --retries 2 --timeout 30 'PyYAML==6.0.3'
    fi
fi

python -c 'import yaml; print("PyYAML", yaml.__version__)'
python --version
go version
javac -version
java -version
node --version
npm --version
