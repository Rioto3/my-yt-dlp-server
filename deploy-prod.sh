#!/bin/bash
git checkout main
git merge devel
git push origin main --force
git checkout devel
