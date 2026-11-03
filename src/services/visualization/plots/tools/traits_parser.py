class TraitsParser:
    TRACE_TRAITS = {"hovertemplate", "mode", "name", "visible"}
    LINE_STYLE_TRAITS = {"color", "dash", "width"}
    SCATTER_STYLE_TRAITS = {"color", "opacity", "symbol", "size"}
    BAR_STYLE_TRAITS = {"color", "opacity"}
    BOXPLOT_STYLE_TRAITS = {"color", "line_color"}
    LINE_TRAITS = LINE_STYLE_TRAITS | TRACE_TRAITS
    SCATTER_TRAITS = SCATTER_STYLE_TRAITS | TRACE_TRAITS
    SERIES_TRAITS = (
        LINE_STYLE_TRAITS
        | SCATTER_STYLE_TRAITS
        | BAR_STYLE_TRAITS
        | BOXPLOT_STYLE_TRAITS
        | TRACE_TRAITS
    )
    TEXT_TRAITS = {"color", "fontsize", "x", "y", "text"}

    @staticmethod
    def get_trait_value(trait: dict | None, trait_name, default_value):
        return (trait or {}).get(trait_name, default_value)

    @staticmethod
    def get_trait_list(traits: list[dict], type: str) -> list[dict]:
        if not traits:
            return []

        return [trait for trait in traits if trait.get("type") == type]

    @staticmethod
    def filtered_trait(trait: dict, allowed: set) -> dict:
        return {k: v for k, v in trait.items() if k in allowed}
