.PHONY: install

install:
	@if [ -e "$(HOME)/.agents" ] && [ ! -L "$(HOME)/.agents" ]; then \
		echo "Error: $(HOME)/.agents exists and is not a symlink. Remove or rename it first."; \
		exit 1; \
	fi
	ln -sfn "$(CURDIR)" "$(HOME)/.agents"
