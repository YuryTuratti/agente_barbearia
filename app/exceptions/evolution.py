class EvolutionClientError(Exception):
    pass


class EvolutionTemporaryError(EvolutionClientError):
    pass


class EvolutionPermanentError(EvolutionClientError):
    pass
