#!/bin/bash

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

cd $SCRIPT_DIR
pip install -e .

cat <<"EOF" | iris session iris -U %SYS
zpm "load -v /home/irisowner/iterm"
halt
EOF

cat <<"EOF" | iris session iris -U USER
do $system.OBJ.Load("/home/irisowner/iterm/src/clock.mac", "ck")
do $system.OBJ.Load("/home/irisowner/iterm/src/term.mac", "ck")
halt
EOF