PLUGIN := booxdrop
# Keep in sync with the `version = (...)` tuple in __init__.py.
VERSION := 0.0.10

ZIP := $(PLUGIN)-$(VERSION).zip

.PHONY: zip install dev-install clean

zip:
	@rm -f $(ZIP)
	zip -r $(ZIP) \
	  __init__.py booxdrop.py config.py discovery.py \
	  plugin-import-name-booxdrop.txt \
	  about.txt README.md \
	  -x '*.pyc' -x '__pycache__/*' -x '.git/*'
	@echo "Built $(ZIP)"

install: zip
	calibre-customize -a $(ZIP)

dev-install:
	-calibre-debug -s
	calibre-customize -b .

clean:
	rm -f *.zip
	find . -name __pycache__ -type d -exec rm -rf {} +
	find . -name '*.pyc' -delete
