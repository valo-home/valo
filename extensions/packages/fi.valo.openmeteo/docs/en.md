## What it does

Fetches the Open-Meteo forecast for the home coordinates: current temperature, feels like, humidity, precipitation, wind and gusts, cloud cover, pressure, hourly forecast for three days and a daily forecast. Separately fetches air quality (European index EAQI, PM2.5, PM10) and pollen concentration. No API key is needed.

Creates the devices "Open-Meteo" and "Open-Meteo Air", the **Weather** page, the **Weather now** widget and flow conditions. Another city can be chosen in the widget settings, search works in Ukrainian, Russian and English.

## One-time setup

1. Set the home coordinates in System, Home. For another place fill **Latitude** and **Longitude** in the extension settings (for example 60.2055 and 24.6559)
2. Install the extension
3. If air quality is not needed, choose `off` in **Air quality**

The forecast refreshes every 30 minutes, air quality every hour. The `demo` source shows made up data without network requests.

## How to use

- **Precipitation expected** checks the next hours for an hour with at least 0.1 mm at or above the given probability. Notification text can use `{mm}`, the precipitation total
- **Frost expected** fires when the minimum temperature in the window is at or below the threshold, `{min}` is available
- **Heat expected** fires when the maximum temperature is at or above the threshold, `{max}` is available
- **Strong wind** checks gusts in m/s, `{gust}` is available
- **Poor air quality** compares the current EAQI with the threshold (above 60 is poor), `{aqi}` is available
- **High pollen** compares the highest pollen concentration with the threshold in grains per m³, `{pollen}` is available

Put the conditions after a **Schedule** trigger. Device values work in regular compare conditions and dashboards.

## Ready templates

- **Rain in the next hours, close windows** in the morning, afternoon and evening
- **Night frost** at 18:00
- **Storm wind** in the morning and evening
- **Poor air** every hour. Add a command that turns off the supply ventilation after the condition

## Limitations

Pollen is available only for Europe and only in season, otherwise the value is 0.
