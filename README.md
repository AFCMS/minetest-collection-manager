# Minetest Collection Manager

This project aims to help maintaining a collection of Minetest content (mods, games, etc) outside a Minetest user
directory. It allows sharing this collection with multiple Minetest installs.

You just need to provide a JSON config file containing which ContentDB and Git packages you want and an output folder
and it will clone and update everything. It will be also able to sync with a specific folder with your own development
stuff.

**It is done with the idea that all the mods _must_ be updated when possible. It is suitable for personnal collection if
you stay updated to latest Minetest versions, not for maintaining servers.**
