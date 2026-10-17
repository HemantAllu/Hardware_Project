# Runs the example C programs on the RV32IM core in simulation; the real Makefile is extras/Makefile.
#   make add | sub | xor | mul | div | sort | fib | gcd | matmul | primes | muldiv | all | list | test | clean
.PHONY: default
default:
	@$(MAKE) --no-print-directory -C extras all
%:
	@$(MAKE) --no-print-directory -C extras $@
