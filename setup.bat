@echo off
echo ========================================
echo 音频自动化工具 - 环境安装脚本
echo ========================================

echo 创建虚拟环境...
python -m venv venv

echo 激活虚拟环境...
call venv\Scripts\activate.bat

echo 升级pip...
python -m pip install --upgrade pip

echo 安装依赖...
pip install -r requirements.txt

echo ========================================
echo 安装完成！
echo 请运行: python main.py
echo ========================================
pause