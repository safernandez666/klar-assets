# devops-security

[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)](https://github.com/pre-commit/pre-commit)

## Developer environment
To follow the conventions and don't argue about whitespace, we use `pre-commit-hooks`. Here's the short version that you need to do on macOS in this repository to be able to commit to this repository: (for different OS, go figure yourself):
1. `brew install pre-commit tflint`
2. `pre-commit install`
3. `tflint --init`

This will install required dependecies and hooks into Git, so when you try to commit code those hooks/checks will be run, and you will get fixes/failures or warnings about your code. These checks must pass before PR can be merged and validated using github workflows.
