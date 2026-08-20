# Installation and Setup

## HACS Installation

1. Open HACS in Home Assistant.
2. Go to **Integrations**.
3. Open **Custom repositories**.
4. Add this repository URL:

   ```text
   https://github.com/Nornode/ha-wilma-inschool
   ```

5. Choose category **Integration**.
6. Install **Wilma**.
7. Restart Home Assistant.

## Manual Installation

Copy the integration folder into your Home Assistant configuration:

```text
custom_components/wilma
```

Then restart Home Assistant.

## Add the Integration

1. In Home Assistant, go to **Settings** > **Devices & services**.
2. Select **Add integration**.
3. Search for **Wilma**.
4. Enter your Wilma server URL, username, and password.

The server URL should be the school or municipality Wilma address, for example:

```text
https://espoo.inschool.fi
```

## Options

Use **Configure** on the integration card to adjust:

- Polling interval in minutes.
- Whether to fetch only unread messages.
- Whether to disable the full-content fetch limit for messages.

Lower polling intervals can make automations feel more immediate, but they also create more requests to Wilma.
