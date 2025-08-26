# set the basf2 release dir in activate.sh

echo ""
echo ""
echo ""
echo ""

workdir=`pwd`
cd ../basf2
source activate.sh
scons -j 4
cd $workdir

echo ""

which basf2

echo ""
echo ""
echo ""
echo ""
