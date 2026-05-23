#!/usr/bin/env bash

# Elegant Android SDK & Emulator Setup Script for macOS (Apple Silicon/arm64)
# Designed for the Autonomous Player Fleet Dashboard

set -euo pipefail

# Color codes for clean output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}====================================================${NC}"
echo -e "${BLUE}   Android SDK & Emulator Auto-Installer for Mac    ${NC}"
echo -e "${BLUE}====================================================${NC}"

# 1. Check CPU Architecture
ARCH=$(uname -m)
if [ "$ARCH" != "arm64" ]; then
    echo -e "${YELLOW}Warning: This script is optimized for Apple Silicon (M1/M2/M3/M4).${NC}"
    echo -e "${YELLOW}You are running on: $ARCH. Adjusting system image selections.${NC}"
    SYS_IMG_ARCH="x86_64"
else
    echo -e "${GREEN}✓ Apple Silicon (arm64) detected.${NC}"
    SYS_IMG_ARCH="arm64-v8a"
fi

# 2. Check Homebrew
if ! command -v brew &>/dev/null; then
    echo -e "${RED}Error: Homebrew is not installed.${NC}"
    echo -e "Please install Homebrew first by running:"
    echo -e "  /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
    exit 1
else
    echo -e "${GREEN}✓ Homebrew is installed.${NC}"
fi

# 3. Install Java (Temurin JDK 17) via Homebrew
echo -e "\n${BLUE}[1/5] Checking Java Environment...${NC}"
if command -v java &>/dev/null && java -version 2>&1 | grep -q "17"; then
    echo -e "${GREEN}✓ Java 17 (or compatible) is already installed.${NC}"
else
    echo -e "${YELLOW}Java 17 is required by Android SDK command line tools.${NC}"
    echo -e "${YELLOW}Installing Eclipse Temurin JDK 17 via Homebrew Cask...${NC}"
    echo -e "${YELLOW}Note: macOS may ask for your password to authorize the JDK installation.${NC}"
    brew install --cask temurin
fi

# 4. Install Android Command Line Tools via Homebrew
echo -e "\n${BLUE}[2/5] Installing Android Command Line Tools Cask...${NC}"
if [ -d "/opt/homebrew/share/android-commandlinetools" ] || brew list --cask android-commandlinetools &>/dev/null; then
    echo -e "${GREEN}✓ android-commandlinetools cask is already installed.${NC}"
else
    brew install --cask android-commandlinetools
fi

# 5. Create Android SDK folder structure inside standard macOS directory
echo -e "\n${BLUE}[3/5] Setting up Android SDK Folder Structure...${NC}"
SDK_DIR="$HOME/Library/Android/sdk"
mkdir -p "$SDK_DIR"

# Link Homebrew's commandlinetools into the standard Library location so they behave natively
# This lets both our fleet manager and standard tools access the binaries in one central place
mkdir -p "$SDK_DIR/cmdline-tools"
if [ ! -L "$SDK_DIR/cmdline-tools/latest" ] && [ ! -d "$SDK_DIR/cmdline-tools/latest" ]; then
    echo -e "Linking Homebrew command-line tools into $SDK_DIR/cmdline-tools/latest"
    # Locate cellar path
    CELLAR_PATH="/opt/homebrew/share/android-commandlinetools"
    if [ -d "$CELLAR_PATH" ]; then
        ln -s "$CELLAR_PATH" "$SDK_DIR/cmdline-tools/latest"
    else
        echo -e "${RED}Error: Homebrew command line tools path not found at $CELLAR_PATH.${NC}"
        exit 1
    fi
fi

# 6. Configure Shell Environment variables (~/.zshrc)
echo -e "\n${BLUE}[4/5] Configuring Environment Variables in ~/.zshrc...${NC}"
ZSHRC="$HOME/.zshrc"
ENV_CHANGED=false

declare -a ENV_LINES=(
    "export ANDROID_HOME=\"\$HOME/Library/Android/sdk\""
    "export PATH=\"\$ANDROID_HOME/cmdline-tools/latest/bin:\$PATH\""
    "export PATH=\"\$ANDROID_HOME/emulator:\$PATH\""
    "export PATH=\"\$ANDROID_HOME/platform-tools:\$PATH\""
)

for line in "${ENV_LINES[@]}"; do
    if ! grep -Fq "$line" "$ZSHRC" 2>/dev/null; then
        echo "$line" >> "$ZSHRC"
        ENV_CHANGED=true
    fi
done

if [ "$ENV_CHANGED" = true ]; then
    echo -e "${GREEN}✓ Android SDK paths successfully appended to your ~/.zshrc.${NC}"
else
    echo -e "${GREEN}✓ Android SDK paths are already configured in ~/.zshrc.${NC}"
fi

# Set them for the current running script session
export ANDROID_HOME="$HOME/Library/Android/sdk"
export PATH="$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/emulator:$ANDROID_HOME/platform-tools:$PATH"

# 7. Accept SDK Licenses & Download Android components (Emulator and System Image)
echo -e "\n${BLUE}[5/5] Accepting Android Licenses & Provisioning Emulator...${NC}"

# Auto-accept all android licenses
echo "yes" | sdkmanager --licenses || true

echo -e "${BLUE}Downloading SDK packages: platform-tools, emulator, platforms;android-34, and system-image...${NC}"
echo -e "${YELLOW}Note: This may take several minutes depending on your internet connection (approx. 1.5 GB).${NC}"

sdkmanager "platform-tools" "emulator" "platforms;android-34" "system-images;android-34;google_apis;$SYS_IMG_ARCH"

# Create a premium pre-configured AVD (Pixel 7a)
echo -e "\n${BLUE}Creating pre-configured Virtual Device (AVD)...${NC}"
AVD_NAME="Pixel_7a_AVD"

# Check if AVD already exists
if emulator -list-avds 2>/dev/null | grep -q "^$AVD_NAME$"; then
    echo -e "${GREEN}✓ Virtual Device '$AVD_NAME' already exists and is ready.${NC}"
else
    echo "no" | avdmanager create avd \
        -n "$AVD_NAME" \
        -k "system-images;android-34;google_apis;$SYS_IMG_ARCH" \
        -device "pixel_7a" \
        --force
    echo -e "${GREEN}✓ Successfully created Virtual Device: $AVD_NAME${NC}"
fi

echo -e "\n${GREEN}====================================================${NC}"
echo -e "${GREEN}🎉 Android SDK and Emulator Setup Complete!         ${NC}"
echo -e "${GREEN}====================================================${NC}"
echo -e "1. ${YELLOW}IMPORTANT:${NC} Open a NEW Terminal window or run: ${BLUE}source ~/.zshrc${NC}"
echo -e "2. Restart the Fleet backend server to detect your native emulator."
echo -e "3. Open the ${BLUE}Device Manager${NC} inside the web app to manage your native ${AVD_NAME}!"
echo -e "${GREEN}====================================================${NC}"
