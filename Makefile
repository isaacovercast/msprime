# simple makefile for development.

SRC=_msprimemodule.c

ext3: ${SRC}
	python3 setup.py build_ext --inplace

ext3-coverage: ${SRC}
	rm -fR build
	CFLAGS="-coverage" python3 setup.py build_ext --inplace

figs:
	cd docs/asy && make 

docs: ext3 figs 
	cd docs && make clean && make html
	
tags:
	ctags -f TAGS *.c lib/*.[c,h] msprime/*.py tests/*.py

clean:
	rm -fR build
	rm -f *.o *.so
