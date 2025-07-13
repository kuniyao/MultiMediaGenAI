import logging
from pathlib import Path
from typing import AsyncGenerator

from genai_processors.processor import Processor
from genai_processors.content_api import ProcessorPart
from workflows.parts import TranslatedTextPart
from common_utils.output_manager import OutputManager

class FileWriterProcessor(Processor):
    """
    A processor that writes the content of a Part to a file.
    It handles TranslatedTextPart for generic text.
    """
    def __init__(self, output_dir: str):
        super().__init__()
        self.logger = logging.getLogger(self.__class__.__name__)
        self.output_manager = OutputManager(output_dir, self.logger)

    def _get_output_path(self, part: ProcessorPart) -> Path:
        """Determines the output file path based on the part's metadata."""
        original_file = part.metadata.get("original_file", "translated_output.txt")
        target_lang = part.metadata.get("target_lang", "translated")
        p = Path(original_file)
        filename = f"{p.stem}_{target_lang}{p.suffix}"
        return self.output_manager.get_workflow_output_path("documents", filename)

    async def _process(self, part: ProcessorPart) -> AsyncGenerator[ProcessorPart, None]:
        if not isinstance(part, TranslatedTextPart):
            # If it's not a part we know how to write, just pass it through
            yield part
            return

        output_content = part.translated_text
        output_path = self._get_output_path(part)

        self.output_manager.save_file(output_path, output_content)
        self.logger.info(f"Successfully wrote output to: {output_path}")
        
        # Yield the original part so the workflow can continue if needed
        yield part

    async def call(self, stream) -> AsyncGenerator[ProcessorPart, None]:
        """The public method to process a stream of parts."""
        async for part in stream:
            async for processed_part in self._process(part):
                yield processed_part