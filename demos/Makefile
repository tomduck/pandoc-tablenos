
extensions = .pdf .html .epub .tex .docx

dest = $(addprefix out/demo,$(extensions)) \
       $(addprefix out/demo2,$(extensions)) \
       $(addprefix out/demo3,$(extensions))


all: $(dest) 


$(filter out/demo.%,$(dest)): demo.md
$(filter out/demo2.%,$(dest)): demo2.md
$(filter out/demo3.%,$(dest)): demo3.md


out/%.pdf: %.md
	@if [ ! -d $(dir $@) ]; then mkdir -p $(dir $@); fi
	pandoc $< --filter pandoc-tablenos --variable urlcolor=blue -o $@

out/%.html: %.md
	@if [ ! -d $(dir $@) ]; then mkdir -p $(dir $@); fi
	pandoc $< --standalone --filter pandoc-tablenos --include-in-header=headers/header.html -o $@

out/%.epub: %.md
	@if [ ! -d $(dir $@) ]; then mkdir -p $(dir $@); fi
	pandoc $< -t epub3 --filter pandoc-tablenos --include-in-header=headers/header.epub -o $@

out/%:
	@if [ ! -d $(dir $@) ]; then mkdir -p $(dir $@); fi
	pandoc $^ --filter pandoc-tablenos -o $@


restore: clean
	for num in "" 2 3 ; do \
      for ext in $(extensions) ; do \
        git checkout out/demo$$num$$ext ; \
      done ; \
    done


.PHONY: clean

clean:
	rm -rf out
