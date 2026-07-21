.PHONY: install

install:
	@if [ -e "$(HOME)/.agents" ] && [ ! -L "$(HOME)/.agents" ]; then \
		echo "Error: $(HOME)/.agents exists and is not a symlink. Remove or rename it first."; \
		exit 1; \
	fi
	ln -sfn "$(CURDIR)" "$(HOME)/.agents"
	
	@if [ -e "$(HOME)/.claude/skills" ] && [ ! -L "$(HOME)/.claude/skills" ]; then \
		echo "Error: $(HOME)/.claude/skills exists and is not a symlink. Remove or rename it first."; \
		exit 1; \
	fi
	ln -sfn "$(CURDIR)/skills" "$(HOME)/.claude/skills"