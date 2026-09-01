from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Patch a YOLO11 ONNX export to an older opset/IR for MaixHub conversion."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--opset", type=int, default=13)
    parser.add_argument("--ir-version", type=int, default=7)
    args = parser.parse_args()

    if not args.input.is_file():
        raise FileNotFoundError(f"input not found: {args.input.resolve()}")

    try:
        import onnx
    except ImportError as exc:
        raise RuntimeError("onnx is required to patch the model") from exc

    model = onnx.load(str(args.input), load_external_data=False)
    converted = False
    try:
        model = onnx.version_converter.convert_version(model, args.opset)
        converted = True
    except Exception:
        converted = False

    if not converted:
        # Older exporters emit a mix of Split/Resize/Reshape forms that the
        # automatic version converter does not cover. Patch those nodes.
        _patch_legacy_ops(model)

    model.ir_version = args.ir_version
    for opset in model.opset_import:
        if opset.domain in ("", "ai.onnx"):
            opset.version = args.opset

    onnx.checker.check_model(model)
    output = args.output.resolve()
    onnx.save(model, str(output))
    print(f"PATCHED_ONNX={output}")
    return 0


def _patch_legacy_ops(model) -> None:
    import onnx

    inferred = onnx.shape_inference.infer_shapes(model)
    info = {value.name: value for value in inferred.graph.value_info}
    initializers = {item.name: item for item in model.graph.initializer}

    def tensor_dims(name: str) -> list[int | None]:
        if name in info:
            return [
                dim.dim_value if dim.dim_value else None
                for dim in info[name].type.tensor_type.shape.dim
            ]
        if name in initializers:
            return [int(dim) for dim in initializers[name].dims]
        return []

    def split_values(node, axis: int) -> list[int]:
        if len(node.output) < 2:
            raise RuntimeError(f"{node.name}: Split requires at least two outputs")
        first_output = tensor_dims(node.output[0])
        if len(first_output) > axis and first_output[axis] is not None:
            size = int(first_output[axis])
            return [size] * len(node.output)
        input_dims = tensor_dims(node.input[0])
        if len(input_dims) > axis and input_dims[axis] is not None:
            size = int(input_dims[axis])
            if size % len(node.output) != 0:
                raise RuntimeError(f"{node.name}: cannot derive an equal split")
            return [size // len(node.output)] * len(node.output)
        raise RuntimeError(f"{node.name}: cannot derive split sizes")

    for node in model.graph.node:
        if node.op_type == "Resize":
            kept = [attr for attr in node.attribute if attr.name not in {"antialias", "keep_aspect_ratio_policy"}]
            del node.attribute[:]
            node.attribute.extend(kept)
        elif node.op_type == "Reshape":
            kept = [attr for attr in node.attribute if attr.name != "allowzero"]
            del node.attribute[:]
            node.attribute.extend(kept)
        elif node.op_type == "Split":
            kept = [attr for attr in node.attribute if attr.name != "num_outputs"]
            del node.attribute[:]
            node.attribute.extend(kept)
            if len(node.input) == 1:
                axis_attr = next((attr.i for attr in node.attribute if attr.name == "axis"), 0)
                values = split_values(node, axis_attr)
                split_name = f"{node.name}_split"
                tensor = onnx.helper.make_tensor(split_name, onnx.TensorProto.INT64, [len(values)], values)
                model.graph.initializer.append(tensor)
                initializers[split_name] = tensor
                node.input.append(split_name)


if __name__ == "__main__":
    raise SystemExit(main())
