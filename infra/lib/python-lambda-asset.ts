import * as cdk from "aws-cdk-lib";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as path from "path";

/**
 * Build a deployable Python-Lambda code asset from local source
 * packages (Session 0010, resolving Session 0008 OQ #1).
 *
 * Why this exists: our Lambdas depend on local packages (``api``,
 * ``oauth``, ``routing``, ``audit``, ``tools/lookup_patient``) that
 * are not on PyPI. ``lambda.Code.fromAsset`` only ships the path you
 * give it, so the deployed Lambda ``ImportError``s on first invoke.
 *
 * Strategy: run ``pip install -t /asset-output`` inside the Lambda
 * runtime image. Requires Docker locally (cdk runs the bundling
 * container). Package paths are passed with a ``./`` prefix so pip
 * treats them as directories, not PyPI names.
 */
export function pythonLambdaCode(packages: string[]): lambda.Code {
  const repoRoot = path.join(__dirname, "..", "..");
  const pipTargets = packages.map((p) => `./${p}`).join(" ");
  return lambda.Code.fromAsset(repoRoot, {
    assetHashType: cdk.AssetHashType.OUTPUT,
    exclude: [
      "**/__pycache__",
      "**/*.pyc",
      "**/*.egg-info",
      "**/.pytest_cache",
      "**/.venv",
      "**/node_modules",
      "infra/cdk.out",
      "web",
      "ci",
      "agent",
      "docs",
      "scripts",
      "secrets",
      "**/tests",
      ".env",
      ".git",
    ],
    bundling: {
      image: lambda.Runtime.PYTHON_3_12.bundlingImage,
      command: [
        "bash",
        "-c",
        `pip install --quiet --no-cache-dir -t /asset-output ${pipTargets}`,
      ],
    },
  });
}
