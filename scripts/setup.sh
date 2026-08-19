#!/bin/bash
set -e

# Install development dependencies
pip install -r requirements_dev.txt

# Install pre-commit hooks if pre-commit is installed
#if command -v pre-commit &> /dev/null; then
#  pre-commit install
#fi

# Create symlinks for development if not already done
HA_PATH="$PWD/.homeassistant"
CUSTOM_COMPONENTS_PATH="$HA_PATH/config/custom_components"
TARGET_PATH="$CUSTOM_COMPONENTS_PATH/wilma"

if [ -d "$HA_PATH" ] && [ ! -L "$TARGET_PATH" ]; then
  echo "Creating symlink for development..."
  
  # Create custom_components directory if it doesn't exist
  mkdir -p "$CUSTOM_COMPONENTS_PATH"
  
  # Remove target directory if it exists but is not a symlink
  if [ -d "$TARGET_PATH" ] && [ ! -L "$TARGET_PATH" ]; then
    echo "Removing existing directory $TARGET_PATH"
    rm -rf "$TARGET_PATH"
  fi
  
  # Create symlink
  ln -sf "$(pwd)/custom_components/wilma" "$TARGET_PATH"
  echo "Symlink created at $TARGET_PATH"
fi

echo "Setup completed successfully!"
echo ""
echo "Next steps:"
echo "1. Activate the virtual environment with: source venv/bin/activate"
echo "2. Run tests with: pytest"
echo "3. Restart Home Assistant after making changes"