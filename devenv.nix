{ pkgs, ... }:

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
  ];

  languages.python = {
    enable = true;
    uv = {
      enable = true;
      sync.enable = true;
    };
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

    ruff-format = {
      enable = true;
      name = "ruff-format";
      description = "Format Python code with ruff";
      entry = "${pkgs.ruff}/bin/ruff format --check src/";
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
  '';
}
