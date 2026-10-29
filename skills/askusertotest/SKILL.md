---
name: askusertotest
description: "Ask the user to test the fix."
disable-model-invocation: false
---

Render a draft reply in the chat that asks the user of the issue to test the fix that we have submitted as a draft PR. After submission also post a comment in the pull request saying that we are awaiting the user's test feedback before merging it. 

Here is a template that I want you to use to communicate with the user. Either post the HAOS version or the Docker install version based on whatever setup the user is running.. Fill in the blanks for the server repo and potentially the front end repo when applicable. 

Template:

We have a fix available, could you please test this with? This won't interfere with your existing installation of MA, as it is a completely isolated installation of MA.

## HAOS
- Go to 'Settings > Apps' and stop your current MA App
- Click 'Install an app' and install the 'Music Assistant DEV SERVER'
- Go to the configuration tab of the App
- Type `` for server_repo
- Leave the frontend_repo blank
- Start the app. This will take longer than you are used to
- Test if the issue has been resolved

## Docker installs
- Make sure to use a different data dir to prevent running dev from interfering with your stable instance
- Execute the following commands
```
git clone https://github.com/music-assistant/home-assistant-addon
cd home-assistant-addon/music_assistant_dev
docker build -t ma-dev .
```
```
mkdir -p ma-data
echo '{"server_repo": ""}' > ma-data/options.json
docker run --rm -it --network host -v "$(pwd)/ma-data:/data" ma-dev
```