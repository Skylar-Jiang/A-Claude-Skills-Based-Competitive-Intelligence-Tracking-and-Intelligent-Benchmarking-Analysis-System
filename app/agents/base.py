from abc import ABC, abstractmethod

from langchain_core.runnables import RunnableLambda, RunnableSequence
from pydantic import BaseModel


class BaseScaffoldAgent[InputT: BaseModel, OutputT: BaseModel](ABC):
    input_model: type[InputT]
    output_model: type[OutputT]

    def __init__(self) -> None:
        self.chain: RunnableSequence = (
            RunnableLambda(self._validate_input)
            | RunnableLambda(self._run_stub)
            | RunnableLambda(self._validate_output)
        )

    def run(self, context: InputT) -> OutputT:
        return self.chain.invoke(context)

    def _validate_input(self, value: InputT | dict[str, object]) -> InputT:
        return self.input_model.model_validate(value)

    @abstractmethod
    def _run_stub(self, context: InputT) -> OutputT | dict[str, object]:
        """Run the mode-specific implementation behind the shared LCEL validation chain."""

    def _validate_output(self, value: OutputT | dict[str, object]) -> OutputT:
        return self.output_model.model_validate(value)
