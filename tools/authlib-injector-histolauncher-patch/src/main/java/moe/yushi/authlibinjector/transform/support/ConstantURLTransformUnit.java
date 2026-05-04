package moe.yushi.authlibinjector.transform.support;

import static moe.yushi.authlibinjector.internal.org.objectweb.asm.Opcodes.ARETURN;
import static moe.yushi.authlibinjector.internal.org.objectweb.asm.Opcodes.ASM9;

import java.util.Optional;

import moe.yushi.authlibinjector.httpd.URLProcessor;
import moe.yushi.authlibinjector.internal.org.objectweb.asm.ClassVisitor;
import moe.yushi.authlibinjector.internal.org.objectweb.asm.MethodVisitor;
import moe.yushi.authlibinjector.transform.CallbackMethod;
import moe.yushi.authlibinjector.transform.LdcTransformUnit;
import moe.yushi.authlibinjector.transform.TransformContext;

public class ConstantURLTransformUnit extends LdcTransformUnit {

	private URLProcessor urlProcessor;
	private static volatile URLProcessor textureUrlProcessor;

	public ConstantURLTransformUnit(URLProcessor urlProcessor) {
		this.urlProcessor = urlProcessor;
		textureUrlProcessor = urlProcessor;
	}

	@Override
	protected Optional<String> transformLdc(String input) {
		return urlProcessor.transformURL(input);
	}

	@CallbackMethod
	public static String transformTextureUrl(String input) {
		URLProcessor processor = textureUrlProcessor;
		if (processor == null || input == null) {
			return input;
		}
		return processor.transformURL(input).orElse(input);
	}

	@Override
	public Optional<ClassVisitor> transform(ClassLoader classLoader, String className, ClassVisitor writer, TransformContext ctx) {
		if ("com.mojang.authlib.minecraft.MinecraftProfileTexture".equals(className)) {
			return Optional.of(new ClassVisitor(ASM9, writer) {
				@Override
				public MethodVisitor visitMethod(int access, String name, String descriptor, String signature, String[] exceptions) {
					MethodVisitor visitor = super.visitMethod(access, name, descriptor, signature, exceptions);
					if ("getUrl".equals(name) && "()Ljava/lang/String;".equals(descriptor)) {
						ctx.markModified();
						return new MethodVisitor(ASM9, visitor) {
							@Override
							public void visitInsn(int opcode) {
								if (opcode == ARETURN) {
									ctx.invokeCallback(this.mv, ConstantURLTransformUnit.class, "transformTextureUrl");
								}
								super.visitInsn(opcode);
							}
						};
					}
					return visitor;
				}
			});
		}

		return super.transform(classLoader, className, writer, ctx);
	}

	@Override
	public String toString() {
		return "Constant URL Transformer";
	}
}