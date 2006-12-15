#! /bin/bash

cd ~mailman/

for i in $*; do
	echo "--- $i ---"
	if [ -e lists/$i/extend.py ]; then
		echo "deja convertie"
	elif [ ! -e lists/$i/config.pck ]; then
		echo "n'existe pas..."
	else
		bin/migrate_to_mysql $i
		bin/remove_members --all --nouserack --noadminack $i
		cp lists/info-diplo/extend.py lists/$i/
	fi
done
