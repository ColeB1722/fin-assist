{ pkgs, config, ... }:

{
  packages = with pkgs; [
    nixfmt-rfc-style
    nil

    python3
    uv
    ruff

    just
    jq
    treefmt

    fd
    fzf
    git
    secretspec
  ];

  languages.python = {
    enable = true;
    uv = {
      enable = true;
      sync = {
        enable = true;
        allGroups = true;
      };
    };
  };

  env = {
    OPENROUTER_API_KEY = config.secretspec.secrets.OPENROUTER_API_KEY or "";
    ANTHROPIC_API_KEY = config.secretspec.secrets.ANTHROPIC_API_KEY or "";
    FIN_GENERAL__DEFAULT_PROVIDER = "openrouter";
    FIN_GENERAL__DEFAULT_MODEL = "google/gemini-2.5-flash";
    FIN_SERVER__LOG_PATH = "./hub.log";
  };

  git-hooks.hooks = {
    treefmt.enable = true;

    ruff-check = {
      enable = true;
      name = "ruff-check";
      description = "Lint Python code with ruff";
      entry = "${pkgs.ruff}/bin/ruff check src/";
      language = "system";
      types = [ "python" ];
      pass_filenames = false;
    };
  };

  enterShell = ''
    echo "fin-assist dev shell"
    echo "Python: $(python --version)"
    echo "uv:     $(uv --version)"
    echo ""
    echo "Commands:"
    echo "  just          - List available tasks"
    echo "  just dev      - Enter dev shell"
    echo "  just fmt      - Format code"
    echo "  just lint     - Run linter"
    echo "  just test     - Run tests"
    echo "  just run      - Run the TUI"
    echo ""
  '';
}
