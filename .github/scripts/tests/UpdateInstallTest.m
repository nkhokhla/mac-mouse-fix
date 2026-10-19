#import <Foundation/Foundation.h>
// Distribution builds strip framework headers; this public class forces loading.
@interface SUUpdater : NSObject
@end

// Exercise the actual Sparkle shipped with MMF against disposable app copies.
@interface SUHost : NSObject
- (instancetype)initWithBundle:(NSBundle *)bundle;
@end
@interface SUSignatures : NSObject
- (instancetype)initWithDsa:(NSString *)dsa ed:(NSString *)ed;
@end
@interface SUUpdateValidator : NSObject
- (instancetype)initWithDownloadPath:(NSString *)path signatures:(SUSignatures *)signatures host:(SUHost *)host;
- (BOOL)validateDownloadPath;
- (BOOL)validateWithUpdateDirectory:(NSString *)directory;
@end
@interface SUPlainInstaller : NSObject
- (instancetype)initWithHost:(SUHost *)host bundlePath:(NSString *)bundlePath installationPath:(NSString *)path fileOperationToolPath:(NSString *)tool;
- (BOOL)performInitialInstallation:(NSError **)error;
- (BOOL)performFinalInstallationProgressBlock:(void (^)(double))progress error:(NSError **)error;
@end

int main(int argc, const char **argv) {
    @autoreleasepool {
        if (argc != 5) return 2;
        [SUUpdater class];
        if (!NSClassFromString(@"SUPlainInstaller")) return 7;
        NSString *oldApp = @(argv[1]);
        NSString *directory = @(argv[2]);
        NSString *newApp = [directory stringByAppendingPathComponent:@"Mac Mouse Fix.app"];
        NSDictionary *newInfo = [NSDictionary dictionaryWithContentsOfFile:[newApp stringByAppendingPathComponent:@"Contents/Info.plist"]];
        SUHost *host = [[NSClassFromString(@"SUHost") alloc] initWithBundle:[NSBundle bundleWithPath:oldApp]];
        SUSignatures *signatures = [[NSClassFromString(@"SUSignatures") alloc] initWithDsa:nil ed:@(argv[4])];
        SUUpdateValidator *validator = [[NSClassFromString(@"SUUpdateValidator") alloc] initWithDownloadPath:@(argv[3]) signatures:signatures host:host];
        if (![validator validateDownloadPath] || ![validator validateWithUpdateDirectory:directory]) return 3;
        // A substituted signature must be rejected by Sparkle itself.
        NSString *bad = [[NSMutableData dataWithLength:64] base64EncodedStringWithOptions:0];
        SUUpdateValidator *tampered = [[NSClassFromString(@"SUUpdateValidator") alloc] initWithDownloadPath:@(argv[3])
            signatures:[[NSClassFromString(@"SUSignatures") alloc] initWithDsa:nil ed:bad] host:host];
        if ([tampered validateDownloadPath]) return 4;
        SUPlainInstaller *installer = [[NSClassFromString(@"SUPlainInstaller") alloc] initWithHost:host bundlePath:newApp
            installationPath:oldApp fileOperationToolPath:@"/usr/bin/false"];
        NSError *error = nil;
        if (![installer performInitialInstallation:&error] ||
            ![installer performFinalInstallationProgressBlock:nil error:&error]) {
            NSLog(@"Disposable update installation failed: %@", error);
            return 5;
        }
        NSDictionary *installed = [NSDictionary dictionaryWithContentsOfFile:[oldApp stringByAppendingPathComponent:@"Contents/Info.plist"]];
        if (![installed[@"CFBundleVersion"] isEqual:newInfo[@"CFBundleVersion"]]) return 6;
        puts("Sparkle validated the signed update, rejected a bad signature, and installed the newer app copy");
    }
    return 0;
}
