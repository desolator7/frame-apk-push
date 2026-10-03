# Contributor's Guide

To contribute to the SteamOS DevKit Client project:
- Open [an issue](https://gitlab.steamos.cloud/devkit/steamos-devkit/-/issues) describing the feature request or bug you're experiencing.
- Fork the repository onto a more permissive source host (such as gitlab or github) under your own account.
  - Check out Steam OS DevKit client to your computer and pull the latest `main`
  - Create a new empty repository in your host of choice
  - Add the new repository as a remote to your checkout `git remote add MYFORK URL`
  - Push the main branch to your fork `git push MYFORK main`
- Make a new branch on your fork and push it to your origin. Name it after the issue number you created on `gitlab.steamos.cloud`.
  - For bugs, `git checkout -b bug/ISSUE_NUMBER`
  - For features, `git checkout -b feature/ISSUE_NUMBER`
  - For documentation updates, `git checkout -b docs/ISSUE_NUMBER`
- Develop and test your change on your fork
- Once your work is ready, go back to the issue you created on `gitlab.steamos.cloud` and either:
  - Link to the branch of your code on your fork, or
  - Link to a merge request on your fork from your working branch to your `main` branch. This makes the code slightly easier to review.
- Communicate further with the SteamOS DevKit Client maintainer(s) via `gitlab.steamos.cloud` until your work is merged.

Thank you for contributing!
